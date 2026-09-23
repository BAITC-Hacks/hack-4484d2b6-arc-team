import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import Database
from app.main import create_app
from app.models import DraftUpdate, Milestone, Proposal, TaskCard
from app.repository import Repository, encode, utc_now
from seed import seed_database

OWNER = {"X-Demo-Business-Id": "business-1"}
OTHER = {"X-Demo-Business-Id": "business-2"}


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.sqlite3")
    seed_database(database)
    return database


@pytest.fixture
def client(db):
    with TestClient(create_app(db.path)) as test_client:
        yield test_client


def test_seed_is_idempotent_and_preserves_user_edits(db):
    repo = Repository(db)
    repo.update_draft("draft-1", "business-1", DraftUpdate(draft_text="Изменено пользователем"))
    assert seed_database(db) == {"businesses": 0, "teams": 0, "drafts": 0}
    assert len(repo.profiles().teams) == 5
    assert len(repo.profiles().businesses) == 2
    assert len(repo.list_tasks("business-1")) == 3
    assert repo.get_task("draft-1", "business-1").draft_text == "Изменено пользователем"


def test_health_profiles_and_openapi(client):
    assert client.get("/health").json() == {"status": "ok", "database": "ok"}
    profiles = client.get("/api/demo/profiles").json()
    assert profiles["businesses"][0]["id"] == "business-1"
    assert profiles["teams"][0]["skills"] == ["аналитика", "веб-разработка"]
    assert client.get("/docs").status_code == 200
    spec = client.get("/openapi.json").json()
    assert "/api/tasks/{task_id}" in spec["paths"]
    assert "/api/tasks/{task_id}/questions" in spec["paths"]
    assert "/api/tasks/{task_id}/generate-card" in spec["paths"]
    assert "/api/tasks/{task_id}/confirm" in spec["paths"]
    assert "/api/tasks/{task_id}/publish" in spec["paths"]
    assert "/api/catalog" in spec["paths"]
    assert "/api/my/proposals" in spec["paths"]


def test_draft_survives_restart_with_original_text(client, db):
    created = client.post("/api/tasks", headers=OWNER, json={"original_text": "Нужно улучшить учёт", "topic": "retail"})
    assert created.status_code == 201
    task = created.json()
    assert task["confirmed_card"] is None
    assert task["confirmed_rating"] is None
    assert task["published_card"] is None
    assert task["status"] == "draft"
    updated = client.patch(f'/api/tasks/{task["id"]}', headers=OWNER,
                           json={"draft_text": "Уточнённый текст", "answers": {"q-data": "Есть CSV"}, "proposed_card": {"title": "Учёт товаров", "data": "Есть CSV"}})
    assert updated.status_code == 200
    with TestClient(create_app(db.path)) as restarted:
        saved = restarted.get(f'/api/tasks/{task["id"]}', headers=OWNER).json()
    assert saved["original_text"] == "Нужно улучшить учёт"
    assert saved["draft_text"] == "Уточнённый текст"
    assert saved["answers"] == {"q-data": "Есть CSV"}
    assert saved["proposed_card"]["title"] == "Учёт товаров"


def test_working_copy_never_overwrites_confirmed_or_published_snapshots(client, db):
    # Isolate PATCH behavior using previously stored snapshots.
    card = TaskCard(title="Подтверждённая задача").model_dump()
    rating = {"score": 0, "level": "draft", "categories": [], "missing_fields": ["context"]}
    questions = [{"id": "q-data", "field": "data", "text": "Какие данные есть?"}]
    with db.connect() as connection:
        connection.execute("UPDATE tasks SET questions=?, confirmed_card=?, confirmed_rating=?, confirmed_at=?, published_card=?, published_rating=?, published_at=?, status='published' WHERE id='draft-1'",
                           (encode(questions), encode(card), encode(rating), utc_now(), encode(card), encode(rating), utc_now()))
    response = client.patch("/api/tasks/draft-1", headers=OWNER, json={"proposed_card": {"title": "Ещё не подтверждено"}, "answers": {"q-data": "CSV"}})
    assert response.status_code == 200
    result = response.json()
    assert result["proposed_card"]["title"] == "Ещё не подтверждено"
    assert result["confirmed_card"] == card
    assert result["published_card"] == card
    assert result["published_rating"] == rating
    assert result["questions"] == questions


def test_profile_selection_and_owner_scoping(client):
    assert client.get("/api/tasks").status_code == 400
    assert client.get("/api/tasks", headers={"X-Demo-Business-Id": "missing"}).status_code == 404
    assert all(task["business_id"] == "business-2" for task in client.get("/api/tasks", headers=OTHER).json())
    assert client.get("/api/tasks/draft-1", headers=OTHER).status_code == 404
    assert client.patch("/api/tasks/draft-1", headers=OTHER, json={"draft_text": "Чужая правка"}).status_code == 404


@pytest.mark.parametrize("body", [{}, {"draft_text": None}, {"draft_text": "  "}, {"status": "published"}, {"confirmed_rating": {"score": 100}}, {"original_text": "Попытка переписать источник"}])
def test_invalid_update_is_rejected_without_data_loss(client, body):
    before = client.get("/api/tasks/draft-1", headers=OWNER).json()
    response = client.patch("/api/tasks/draft-1", headers=OWNER, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert client.get("/api/tasks/draft-1", headers=OWNER).json() == before


def test_invalid_create_does_not_insert(client):
    count = len(client.get("/api/tasks", headers=OWNER).json())
    assert client.post("/api/tasks", headers=OWNER, json={"original_text": "   "}).status_code == 422
    assert len(client.get("/api/tasks", headers=OWNER).json()) == count


def test_relationships_status_constraints_and_transaction_rollback(db):
    now = utc_now()
    with pytest.raises(sqlite3.IntegrityError), db.connect() as connection:
        connection.execute("INSERT INTO proposals (id, task_id, team_id, idea, plan, timeline, created_at) VALUES ('bad', 'missing-task', 'team-1', 'idea', 'plan', 'week', ?)", (now,))
    with pytest.raises(sqlite3.IntegrityError), db.connect() as connection:
        connection.execute("UPDATE tasks SET draft_text='Must roll back' WHERE id='draft-1'")
        connection.execute("UPDATE tasks SET status='published' WHERE id='draft-1'")
    assert Repository(db).get_task("draft-1", "business-1").draft_text != "Must roll back"
    with db.connect() as connection:
        connection.execute("INSERT INTO proposals (id, task_id, team_id, idea, plan, timeline, created_at) VALUES ('proposal-1', 'draft-1', 'team-1', 'idea', 'plan', 'week', ?)", (now,))
        connection.execute("INSERT INTO milestones (id, proposal_id, description, created_at) VALUES ('milestone-1', 'proposal-1', 'demo result', ?)", (now,))
        proposal = Proposal.model_validate(dict(connection.execute("SELECT * FROM proposals WHERE id='proposal-1'").fetchone()))
        milestone = Milestone.model_validate(dict(connection.execute("SELECT * FROM milestones WHERE id='milestone-1'").fetchone()))
    assert proposal.status == "submitted"
    assert proposal.prototype_url is None
    assert milestone.points_awarded == 0
    with pytest.raises(sqlite3.IntegrityError), db.connect() as connection:
        connection.execute("UPDATE milestones SET points_awarded=10 WHERE id='milestone-1'")


def test_seed_failure_rolls_back_all_insertions(tmp_path):
    source = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "demo.json").read_text(encoding="utf-8"))
    source["drafts"][0]["business_id"] = "missing-business"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    database = Database(tmp_path / "empty.sqlite3")
    with pytest.raises(sqlite3.IntegrityError):
        seed_database(database, path)
    assert Repository(database).profiles().businesses == []


def test_startup_creates_empty_schema_without_implicit_seed(tmp_path):
    with TestClient(create_app(tmp_path / "nested" / "empty.sqlite3")) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/demo/profiles").json() == {"businesses": [], "teams": []}
