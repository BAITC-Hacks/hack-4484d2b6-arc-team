from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from app.ai import AIService
from app.config import AISettings
from app.db import Database
from app.main import create_app
from seed import seed_database

OWNER = {"X-Demo-Business-Id": "business-1"}
OTHER = {"X-Demo-Business-Id": "business-2"}
TEAM = {"X-Demo-Team-Id": "team-1"}
OFFER = {"idea": "Прототип учёта", "plan": "Загрузить CSV, показать остатки", "timeline": "Две недели",
         "prototype_url": None, "questions": "Какие товары проверить в первую очередь?"}
RESULT = {"description": "Прототип на тестовом CSV готов", "result_url": "https://example.test/demo"}


def demo_client(tmp_path):
    db = Database(tmp_path / "workflow.sqlite3")
    seed_database(db)
    return TestClient(create_app(db.path, AIService(AISettings())))


def publish(client, card=None, topic="retail"):
    created = client.post("/api/tasks", headers=OWNER,
                          json={"original_text": "Приватный исходный текст", "topic": topic}).json()
    url = f'/api/tasks/{created["id"]}'
    confirmed = client.post(url + "/confirm", headers=OWNER, json={
        "expected_updated_at": created["updated_at"], "proposed_card": card or {"title": "Учёт товаров"}})
    assert confirmed.status_code == 200
    response = client.post(url + "/publish", headers=OWNER, json={"expected_updated_at": confirmed.json()["updated_at"]})
    assert response.status_code == 200
    return response.json()


def offer(client, task_id, team="team-1", body=None):
    return client.post(f"/api/tasks/{task_id}/proposals", headers={"X-Demo-Team-Id": team},
                       json=OFFER if body is None else body)


def select(client, proposal_id, status="selected"):
    return client.patch(f"/api/proposals/{proposal_id}", headers=OWNER, json={"status": status})


def points(client, team_id="team-1"):
    return next(t["points"] for t in client.get("/api/demo/profiles").json()["teams"] if t["id"] == team_id)


def test_public_catalog_filters_order_and_snapshot_privacy(tmp_path):
    with demo_client(tmp_path) as client:
        assert client.get("/api/catalog").json() == []
        assert client.get("/api/catalog/draft-1").status_code == 404
        low = publish(client)
        high = publish(client, {"title": "Доставка", "data": "Есть CSV", "users": "Диспетчер",
                                "constraints": "Две недели"}, "logistics")
        tied = publish(client, {"title": "Вторая доставка", "data": "Есть CSV", "users": "Диспетчер",
                                "constraints": "Две недели"}, "logistics")
        catalog = client.get("/api/catalog").json()
        assert [t["id"] for t in catalog] == [high["id"], tied["id"], low["id"]]
        assert set(catalog[0]) == {"id", "topic", "status", "published_at", "published_card", "published_rating"}
        assert len(client.get("/api/catalog?topic=logistics&readiness=working").json()) == 2
        assert [t["id"] for t in client.get("/api/catalog?readiness=draft").json()] == [low["id"]]
        assert client.get("/api/catalog?topic=retail&readiness=working").json() == []
        assert client.get("/api/catalog", params={"topic": "retail' OR 1=1 --"}).json() == []
        assert client.get("/api/catalog?readiness=invalid").status_code == 422
        before = client.get(f'/api/catalog/{high["id"]}').json()
        edited = client.patch(f'/api/tasks/{high["id"]}', headers=OWNER,
                              json={"topic": "education", "proposed_card": {"title": "Приватная новая карточка"}}).json()
        confirmed = client.post(f'/api/tasks/{high["id"]}/confirm', headers=OWNER,
                                json={"expected_updated_at": edited["updated_at"]}).json()
        assert client.get(f'/api/catalog/{high["id"]}').json() == before
        assert client.get("/api/catalog?topic=education").json() == []
        client.post(f'/api/tasks/{high["id"]}/publish', headers=OWNER,
                    json={"expected_updated_at": confirmed["updated_at"]})
        assert client.get(f'/api/catalog/{high["id"]}').json()["topic"] == "education"
        assert client.get(f'/api/catalog/{high["id"]}').json()["published_rating"]["score"] == 0


def test_complete_workflow_allows_low_rating_multiple_teams_and_persists_points(tmp_path):
    with demo_client(tmp_path) as client:
        task = publish(client)
        assert task["published_rating"]["score"] == 0
        proposals = [offer(client, task["id"], f"team-{i}").json() for i in (1, 2, 3)]
        p1, p2, p3 = proposals
        assert p1["prototype_url"] is None
        assert p1["task_title"] == "Учёт товаров"
        assert p1["team_name"] == "ByteTeam"
        assert select(client, p1["id"]).status_code == 200
        pending = client.get(f'/api/tasks/{task["id"]}/proposals', headers=OWNER).json()
        assert [p["status"] for p in pending] == ["selected", "submitted", "submitted"]
        assert select(client, p2["id"]).status_code == 200
        assert select(client, p3["id"], "rejected").status_code == 200
        mine = client.get("/api/my/proposals", headers=TEAM).json()
        assert len(mine) == 1 and mine[0]["status"] == "selected"
        assert client.get("/api/my/proposals", headers={"X-Demo-Team-Id": "team-4"}).json() == []
        submitted = client.post(f'/api/proposals/{p1["id"]}/milestones', headers=TEAM, json=RESULT)
        assert submitted.status_code == 200
        milestone = submitted.json()
        assert milestone["status"] == "submitted" and milestone["points_awarded"] == 0
        assert points(client) == 0
        confirmed = client.post(f'/api/milestones/{milestone["id"]}/confirm', headers=OWNER)
        assert confirmed.status_code == 200
        assert confirmed.json()["points_awarded"] == 10
        assert confirmed.json()["status"] == "confirmed"
        assert points(client) == 10 and points(client, "team-2") == 0
        assert client.get(f'/api/catalog/{task["id"]}').json()["published_rating"]["score"] == 0
        mine = client.get("/api/my/proposals", headers=TEAM).json()
        assert mine[0]["milestones"] == [confirmed.json()]
        owner_view = client.get(f'/api/tasks/{task["id"]}/proposals', headers=OWNER).json()
        assert owner_view[0]["milestones"] == mine[0]["milestones"]
    with demo_client(tmp_path) as restarted:
        assert points(restarted) == 10
        assert restarted.get("/api/my/proposals", headers=TEAM).json() == mine


def test_permissions_and_decision_transitions(tmp_path):
    with demo_client(tmp_path) as client:
        assert offer(client, "draft-1").status_code == 404
        assert offer(client, "missing").status_code == 404
        task = publish(client)
        path = f'/api/tasks/{task["id"]}/proposals'
        assert client.post(path, headers=OWNER, json=OFFER).status_code == 400
        assert offer(client, task["id"], "missing-team").status_code == 404
        assert client.get(path, headers=OTHER).status_code == 404
        assert client.get(path, headers=TEAM).status_code == 400
        assert client.get("/api/my/proposals", headers=OWNER).status_code == 400
        proposal = offer(client, task["id"]).json()
        decision_path = f'/api/proposals/{proposal["id"]}'
        stage_path = decision_path + "/milestones"
        assert client.patch(decision_path, headers=OTHER, json={"status": "selected"}).status_code == 404
        assert client.patch(decision_path, headers=TEAM, json={"status": "selected"}).status_code == 400
        assert client.post(stage_path, headers=TEAM, json=RESULT).status_code == 409
        assert client.post(stage_path, headers={"X-Demo-Team-Id": "team-2"}, json=RESULT).status_code == 404
        selected = select(client, proposal["id"]).json()
        assert select(client, proposal["id"]).json() == selected
        assert select(client, proposal["id"], "rejected").status_code == 409
        milestone = client.post(stage_path, headers=TEAM, json=RESULT).json()
        confirm_path = f'/api/milestones/{milestone["id"]}/confirm'
        assert client.post(confirm_path, headers=OTHER).status_code == 404
        assert client.post(confirm_path, headers=TEAM).status_code == 400
        assert client.post('/api/milestones/missing/confirm', headers=OWNER).status_code == 404
        assert select(client, "missing").status_code == 404
        assert client.post('/api/proposals/missing/milestones', headers=TEAM, json=RESULT).status_code == 404
        p2 = offer(client, task["id"], "team-2").json()
        assert select(client, p2["id"], "rejected").status_code == 200
        assert client.post(f'/api/proposals/{p2["id"]}/milestones',
                           headers={"X-Demo-Team-Id": "team-2"}, json=RESULT).status_code == 409


def test_parallel_retries_do_not_duplicate_proposals_milestones_or_points(tmp_path):
    with demo_client(tmp_path) as client, ThreadPoolExecutor(max_workers=4) as pool:
        task = publish(client)
        proposals = list(pool.map(lambda _: offer(client, task["id"]), range(4)))
        assert all(r.status_code == 200 for r in proposals)
        assert len({r.json()["id"] for r in proposals}) == 1
        proposal = proposals[0].json()
        assert offer(client, task["id"], body={**OFFER, "idea": "Другое предложение"}).status_code == 409
        assert select(client, proposal["id"]).status_code == 200
        stage_path = f'/api/proposals/{proposal["id"]}/milestones'
        stages = list(pool.map(lambda _: client.post(stage_path, headers=TEAM, json=RESULT), range(4)))
        assert all(r.status_code == 200 for r in stages)
        assert len({r.json()["id"] for r in stages}) == 1
        confirm_path = f'/api/milestones/{stages[0].json()["id"]}/confirm'
        confirmations = list(pool.map(lambda _: client.post(confirm_path, headers=OWNER), range(4)))
        assert all(r.status_code == 200 for r in confirmations)
        assert all(r.json() == confirmations[0].json() for r in confirmations)
        assert points(client) == 10
        assert client.post(stage_path, headers=TEAM, json=RESULT).json() == confirmations[0].json()
        second = client.post(stage_path, headers=TEAM, json={"description": "Второй этап: проверка результатов"}).json()
        assert second["result_url"] is None
        client.post(f'/api/milestones/{second["id"]}/confirm', headers=OWNER)
        assert points(client) == 20
        assert len(client.get('/api/my/proposals', headers=TEAM).json()[0]["milestones"]) == 2


@pytest.mark.parametrize("changes", [{"idea": "  "}, {"plan": None}, {"timeline": ""},
    {"prototype_url": "javascript:alert(1)"}, {"prototype_url": "not a url"},
    {"status": "selected"}, {"team_id": "team-2"}])
def test_invalid_proposal_is_not_saved(tmp_path, changes):
    with demo_client(tmp_path) as client:
        task = publish(client)
        assert offer(client, task["id"], body={**OFFER, **changes}).status_code == 422
        assert client.get('/api/my/proposals', headers=TEAM).json() == []


def test_invalid_decisions_and_milestones_do_not_change_state(tmp_path, monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")
    with demo_client(tmp_path) as client:
        task = publish(client)
        proposal = offer(client, task["id"]).json()
        for body in ({"status": "submitted"}, {"status": "selected", "team_id": "team-2"}, {}):
            assert client.patch(f'/api/proposals/{proposal["id"]}', headers=OWNER, json=body).status_code == 422
        select(client, proposal["id"])
        for body in ({"description": " "}, {"description": "Готово", "points_awarded": 100},
                     {"description": "Готово", "result_url": "file:///private"}):
            assert client.post(f'/api/proposals/{proposal["id"]}/milestones', headers=TEAM, json=body).status_code == 422
        assert client.get('/api/my/proposals', headers=TEAM).json()[0]["milestones"] == []
        assert points(client) == 0
        response = client.options(f'/api/tasks/{task["id"]}/proposals', headers={
            "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type,X-Demo-Team-Id"})
        assert response.status_code == 200


@pytest.mark.parametrize("fields,score,level", [
    ([], 0, "draft"),
    (["data", "expected_result", "contact"], 39, "draft"),
    (["data", "context", "need"], 40, "working"),
    (["data", "expected_result", "context", "need", "users", "contact"], 69, "working"),
    (["data", "expected_result", "success_criteria", "context", "need"], 70, "ready"),
    (["need", "data", "expected_result", "success_criteria", "constraints", "users", "interaction_format"], 86, "ready"),
    (["context", "need", "data", "expected_result", "success_criteria", "constraints", "users"], 90, "priority"),
    (["context", "need", "data", "expected_result", "success_criteria", "constraints", "users", "contact", "interaction_format"], 100, "priority"),
])
def test_real_card_rating_survives_confirmation_publication_and_catalog_filter(tmp_path, fields, score, level):
    with demo_client(tmp_path) as client:
        task = publish(client, {"title": "Проверка готовности", **{field: "Сведения бизнеса" for field in fields}})
        rating = task["confirmed_rating"]
        assert rating["score"] == score
        assert rating["level"] == level
        assert sum(c["points"] for c in rating["categories"]) == score
        assert not set(fields) & set(rating["missing_fields"])
        public = client.get(f'/api/catalog/{task["id"]}').json()
        assert public["published_rating"] == rating
        filtered = client.get('/api/catalog', params={"readiness": level}).json()
        assert filtered == [public]
        assert offer(client, task["id"]).status_code == 200


def test_ai_to_two_selected_teams_and_pending_stage_survives_restarts(tmp_path):
    with demo_client(tmp_path) as client:
        response = client.post('/api/tasks', headers=OWNER,
                               json={"original_text": "У нас путаются остатки товаров.", "topic": "retail"})
        assert response.status_code == 201
        url = '/api/tasks/' + response.json()["id"]
        assert client.post(url + '/questions', headers=OWNER, json={"mode": "local"}).status_code == 200
        generated = client.post(url + '/generate-card', headers=OWNER,
                                json={"mode": "local", "answers": {"q-data": "Есть тестовый CSV."}})
        assert generated.status_code == 200
        confirmed = client.post(url + '/confirm', headers=OWNER,
                                json={"expected_updated_at": generated.json()["task"]["updated_at"]})
        assert confirmed.status_code == 200
        published = client.post(url + '/publish', headers=OWNER,
                                json={"expected_updated_at": confirmed.json()["updated_at"]})
        assert published.status_code == 200
        task = published.json()
        assert task["published_rating"]["score"] == 30
        milestones = []
        for team_id in ('team-1', 'team-2'):
            proposal = offer(client, task["id"], team_id)
            assert proposal.status_code == 200
            assert select(client, proposal.json()["id"]).status_code == 200
            result = client.post(f'/api/proposals/{proposal.json()["id"]}/milestones',
                                 headers={"X-Demo-Team-Id": team_id}, json=RESULT)
            assert result.status_code == 200
            milestones.append(result.json())
        first = client.post(f'/api/milestones/{milestones[0]["id"]}/confirm', headers=OWNER)
        assert first.status_code == 200
        assert points(client) == 10 and points(client, 'team-2') == 0
        before = client.get(url + '/proposals', headers=OWNER).json()
    with demo_client(tmp_path) as restarted:
        assert restarted.get(url, headers=OWNER).json() == task
        assert restarted.get(url + '/proposals', headers=OWNER).json() == before
        assert points(restarted) == 10 and points(restarted, 'team-2') == 0
        assert restarted.post(f'/api/milestones/{milestones[0]["id"]}/confirm', headers=OWNER).json() == first.json()
        second = restarted.post(f'/api/milestones/{milestones[1]["id"]}/confirm', headers=OWNER)
        assert second.status_code == 200 and second.json()["points_awarded"] == 10
        assert points(restarted) == points(restarted, 'team-2') == 10
        public = restarted.get(f'/api/catalog/{task["id"]}').json()
        assert public["published_rating"] == task["published_rating"]
    with demo_client(tmp_path) as restarted:
        assert points(restarted) == points(restarted, 'team-2') == 10
        with restarted.app.state.db.connect() as connection:
            assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert connection.execute('PRAGMA foreign_key_check').fetchall() == []


def test_competing_manual_decisions_have_one_winner_without_affecting_other_teams(tmp_path):
    with demo_client(tmp_path) as client, ThreadPoolExecutor(max_workers=2) as pool:
        task = publish(client)
        proposal = offer(client, task["id"]).json()
        other = offer(client, task["id"], 'team-2').json()
        barrier = Barrier(2, timeout=10)

        def decide(status):
            barrier.wait()
            return select(client, proposal["id"], status)

        results = list(pool.map(decide, ['selected', 'rejected']))
        assert sorted(r.status_code for r in results) == [200, 409]
        winner = next(r.json() for r in results if r.status_code == 200)
        loser = next(r.json() for r in results if r.status_code == 409)
        assert loser['error']['code'] == 'decision_conflict'
        stored = client.get(f'/api/tasks/{task["id"]}/proposals', headers=OWNER).json()
        assert stored == [winner, other]
        assert other['status'] == 'submitted'
        assert points(client) == points(client, 'team-2') == 0
