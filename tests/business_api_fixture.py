"""TEST ONLY: workflow HTTP responses and failure injection for the owner UI.

Not imported by app/ or seed.py; not an implementation of the team's backend.
Matches feat/backend-workflow's embedded milestones and terminal decisions.
"""
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
import time
from typing import Literal

from fastapi import Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.models import Milestone, Proposal, TaskCard


class FixtureDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["selected", "rejected"]


class FixtureProposalView(Proposal):
    team_name: str
    task_title: str
    milestones: list[Milestone] = Field(default_factory=list)


class DashboardFixture:
    def __init__(self, app, repository):
        self.repository = repository
        self.lock = Lock()
        self.decisions = []
        self.confirmations = []
        self.fail_decision = False
        self.fail_confirmation = False
        self.bad_response = False
        now = datetime.now(timezone.utc).isoformat()
        self.proposals = [{
            "id": f"proposal-{index}", "task_id": "draft-1", "team_id": f"team-{(index - 1) % 5 + 1}",
            "idea": '<img src=x onerror="window.dashboardXss=true"> Учебная идея' if index == 1 else f"Идея {index}",
            "plan": "Изучить данные. Подготовить прототип. Проверить результат с бизнесом.",
            "timeline": f"{index + 1} недель", "prototype_url": None if index == 1 else "javascript:alert(1)" if index == 2 else "https://example.test/prototype",
            "questions": "Когда можно обсудить данные?", "status": "selected" if index == 3 else "rejected" if index == 4 else "submitted",
            "created_at": now, "decided_at": None,
        } for index in range(1, 7)]
        self.milestones = [{
            "id": f"milestone-{index}", "proposal_id": "proposal-3", "description": f"Учебный результат этапа {index}: описание проверки.",
            "result_url": None if index == 3 else "https://example.test/result", "status": "confirmed" if index == 2 else "submitted",
            "points_awarded": 13 if index == 2 else 0, "created_at": now, "confirmed_at": now if index == 2 else None,
        } for index in range(1, 4)]
        task = repository.get_task("draft-1", "business-1")
        task = repository.confirm_task(task.id, "business-1", task.updated_at, TaskCard(title="Учебная задача магазина"))
        repository.publish_task(task.id, "business-1", task.updated_at)

        def own_task(task_id, owner):
            if repository.get_task(task_id, owner) is None:
                raise HTTPException(404, "Задача не найдена")

        def own_proposal(proposal_id, owner):
            proposal = next((item for item in self.proposals if item["id"] == proposal_id), None)
            if not proposal:
                raise HTTPException(404, "Предложение не найдено")
            own_task(proposal["task_id"], owner)
            return proposal

        def view(item):
            return {**deepcopy(item), "team_name": f"Учебная команда {item['team_id']}",
                    "task_title": "Учебная задача магазина",
                    "milestones": [deepcopy(stage) for stage in self.milestones if stage["proposal_id"] == item["id"]]}

        @app.get("/api/tasks/{task_id}/proposals", response_model=list[FixtureProposalView])
        def proposals(task_id: str, x_demo_business_id: str = Header()):
            own_task(task_id, x_demo_business_id)
            # JSONResponse deliberately includes an unsafe URL to test client rendering.
            return JSONResponse([view(item) for item in self.proposals if item["task_id"] == task_id])

        @app.patch("/api/proposals/{proposal_id}", response_model=FixtureProposalView)
        def decide(proposal_id: str, payload: FixtureDecision, x_demo_business_id: str = Header()):
            with self.lock:
                item = own_proposal(proposal_id, x_demo_business_id)
                time.sleep(.2)
                if self.fail_decision:
                    self.fail_decision = False
                    return JSONResponse({"error": {"message": "Тестовая ошибка решения"}}, status_code=503)
                if item["status"] != "submitted":
                    if item["status"] != payload.status:
                        raise HTTPException(409, "Решение уже принято")
                    return JSONResponse(view(item))
                self.decisions.append((proposal_id, payload.status))
                item["status"] = payload.status
                item["decided_at"] = datetime.now(timezone.utc).isoformat()
                if self.bad_response:
                    self.bad_response = False
                    return JSONResponse({"status": payload.status})
                return JSONResponse(view(item))

        @app.post("/api/milestones/{milestone_id}/confirm", response_model=Milestone)
        def confirm(milestone_id: str, x_demo_business_id: str = Header()):
            with self.lock:
                item = next((entry for entry in self.milestones if entry["id"] == milestone_id), None)
                if not item:
                    raise HTTPException(404, "Этап не найден")
                parent = own_proposal(item["proposal_id"], x_demo_business_id)
                if parent["status"] != "selected":
                    raise HTTPException(409, "Команда не выбрана")
                time.sleep(.2)
                if self.fail_confirmation:
                    self.fail_confirmation = False
                    return JSONResponse({"error": {"message": "Тестовая ошибка этапа"}}, status_code=503)
                self.confirmations.append(milestone_id)
                if item["status"] != "confirmed":
                    item.update(status="confirmed", points_awarded=7, confirmed_at=datetime.now(timezone.utc).isoformat())
                return deepcopy(item)

        app.openapi_schema = None
