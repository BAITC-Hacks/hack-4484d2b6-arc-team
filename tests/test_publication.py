import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ai import AIService
from app.config import AISettings
from app.db import Database
from app.main import create_app
from app.models import TaskCard
from app.repository import Repository, encode, utc_now
from seed import seed_database

OWNER = {"X-Demo-Business-Id": "business-1"}
OTHER = {"X-Demo-Business-Id": "business-2"}
URL = "/api/tasks/draft-1"


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "publication.sqlite3")
    seed_database(database)
    return database


@pytest.fixture
def client(db):
    with TestClient(create_app(db.path, AIService(AISettings()))) as client:
        yield client


def read(client):
    return client.get(URL, headers=OWNER).json()


def action(client, operation, task, **body):
    return client.post(f"{URL}/{operation}", headers=OWNER,
                       json={"expected_updated_at": task["updated_at"], **body})


def confirm(client, card=None):
    response = action(client, "confirm", read(client), **({"proposed_card": card} if card is not None else {}))
    assert response.status_code == 200, response.text
    return response.json()


def test_zero_score_can_publish_and_survives_restart(client, db):
    confirmed = confirm(client, {"title": "Нужно улучшить учёт"})
    assert confirmed["status"] == "draft"
    assert confirmed["confirmed_rating"]["score"] == 0
    assert confirmed["confirmed_rating"]["level"] == "draft"
    assert confirmed["published_card"] is None
    assert not confirmed["has_unconfirmed_changes"]
    assert confirmed["has_unpublished_changes"]
    response = action(client, "publish", confirmed)
    assert response.status_code == 200
    published = response.json()
    assert published["status"] == "published"
    assert published["published_rating"]["score"] == 0
    assert published["published_card"] == confirmed["confirmed_card"]
    assert published["published_at"] is not None
    assert not published["has_unpublished_changes"]
    with TestClient(create_app(db.path, AIService(AISettings()))) as restarted:
        assert read(restarted) == published


def test_confirmation_required_and_invalid_title_does_not_erase_work(client):
    before = read(client)
    assert action(client, "publish", before).status_code == 409
    response = action(client, "confirm", before, proposed_card={"title": "???", "data": "Есть CSV"})
    assert response.status_code == 422
    assert read(client) == before


def test_edits_and_reconfirmation_keep_old_publication_until_explicit_publish(client):
    first = confirm(client, {"title": "Учёт товаров", "data": "CSV на 500 строк", "context": "Учёт вручную"})
    assert first["confirmed_rating"]["score"] == 30
    published = action(client, "publish", first).json()
    edited = client.patch(URL, headers=OWNER, json={"topic": "logistics", "proposed_card": {
        "title": "Новое название", "users": "Кладовщик"}}).json()
    assert edited["has_unconfirmed_changes"]
    assert edited["confirmed_card"] == edited["published_card"] == published["published_card"]
    assert edited["published_topic"] == published["topic"]
    assert action(client, "publish", edited).status_code == 409
    assert read(client) == edited
    confirmed = confirm(client)
    assert confirmed["confirmed_rating"]["score"] == 10  # Removing fields lowers the score.
    assert confirmed["confirmed_topic"] == "logistics"
    assert confirmed["published_rating"]["score"] == 30
    assert confirmed["published_card"] == published["published_card"]
    assert not confirmed["has_unconfirmed_changes"]
    assert confirmed["has_unpublished_changes"]
    response = action(client, "publish", confirmed)
    assert response.status_code == 200
    updated = response.json()
    assert updated["published_card"] == confirmed["confirmed_card"]
    assert updated["published_rating"] == confirmed["confirmed_rating"]
    assert updated["published_topic"] == "logistics"
    assert updated["published_at"] == published["published_at"]
    assert updated["original_text"] == published["original_text"]


def test_topic_only_edit_requires_confirmation(client):
    confirmed = confirm(client, {"title": "Учёт"})
    edited = client.patch(URL, headers=OWNER, json={"topic": "education"}).json()
    assert edited["confirmed_topic"] == confirmed["topic"]
    assert action(client, "publish", edited).status_code == 409
    confirmed = confirm(client)
    published = action(client, "publish", confirmed).json()
    assert published["published_topic"] == "education"


def test_fresh_repeated_actions_are_idempotent(client):
    confirmed = confirm(client, {"title": "Учёт"})
    assert action(client, "confirm", confirmed).json() == confirmed
    published = action(client, "publish", confirmed).json()
    assert action(client, "publish", published).json() == published
    assert action(client, "confirm", published).json() == published


@pytest.mark.parametrize("operation", ["confirm", "publish"])
def test_stale_request_cannot_overwrite_newer_work(client, operation):
    stale = confirm(client, {"title": "Учёт"})
    current = client.patch(URL, headers=OWNER, json={"draft_text": "Новый ввод бизнеса"}).json()
    response = action(client, operation, stale)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "task_changed"
    assert read(client) == current


@pytest.mark.parametrize("operation", ["confirm", "publish"])
def test_owner_scoping_and_missing_task(client, operation):
    task = read(client)
    body = {"expected_updated_at": task["updated_at"]}
    assert client.post(f"{URL}/{operation}", headers=OTHER, json=body).status_code == 404
    assert client.post(f"/api/tasks/missing/{operation}", headers=OWNER, json=body).status_code == 404
    assert client.post(f"{URL}/{operation}", json=body).status_code == 400
    assert read(client) == task


@pytest.mark.parametrize("operation,body", [
    ("confirm", {}), ("publish", {}),
    ("confirm", {"expected_updated_at": "2026-09-23T10:00:00"}),
    ("confirm", {"proposed_card": None}),
    ("confirm", {"confirmed_rating": {"score": 100}}),
    ("publish", {"published_rating": {"score": 100}}),
    ("confirm", {"proposed_card": {"title": "Учёт", "data": None}}),
])
def test_invalid_requests_cannot_change_task(client, operation, body):
    before = read(client)
    if body and "expected_updated_at" not in body:
        body = {"expected_updated_at": before["updated_at"], **body}
    assert client.post(f"{URL}/{operation}", headers=OWNER, json=body).status_code == 422
    assert read(client) == before


def test_local_ai_to_confirmation_and_publication(client):
    questions = client.post(f"{URL}/questions", headers=OWNER, json={"mode": "local"})
    assert questions.status_code == 200
    generated = client.post(f"{URL}/generate-card", headers=OWNER,
                            json={"mode": "local", "answers": {"q-data": "Есть CSV"}}).json()["task"]
    assert generated["confirmed_rating"] is None
    confirmed = action(client, "confirm", generated).json()
    assert confirmed["confirmed_rating"]["score"] > 0
    assert confirmed["card_ai"]["mode"] == "local"
    assert action(client, "publish", confirmed).status_code == 200
    regenerated = client.post(f"{URL}/generate-card", headers=OWNER,
                              json={"mode": "local", "answers": {"q-data": "Не знаю"}}).json()["task"]
    assert regenerated["has_unconfirmed_changes"]
    assert regenerated["published_rating"] == confirmed["confirmed_rating"]
    edited = confirm(client, {"title": "Ручная карточка"})
    assert edited["card_ai"] is None
    assert edited["published_rating"] == confirmed["confirmed_rating"]


def test_v2_migration_preserves_published_data_and_backfills_topics(tmp_path):
    path = tmp_path / "v2.sqlite3"
    card = TaskCard(title="Старая карточка").model_dump()
    rating = {"score": 0, "level": "draft", "categories": [], "missing_fields": []}
    now = utc_now()
    with sqlite3.connect(path) as connection:
        connection.executescript((Path(__file__).resolve().parents[1] / "app" / "schema.sql").read_text(encoding="utf-8"))
        connection.execute("ALTER TABLE tasks ADD COLUMN questions_ai TEXT")
        connection.execute("ALTER TABLE tasks ADD COLUMN card_ai TEXT")
        connection.execute("PRAGMA user_version=2")
        connection.execute("INSERT INTO business_profiles VALUES ('legacy', 'Legacy', 'retail', '', 1)")
        connection.execute("INSERT INTO tasks (id, business_id, original_text, draft_text, topic, proposed_card, confirmed_card, confirmed_rating, confirmed_at, published_card, published_rating, published_at, status, created_at, updated_at) VALUES ('legacy-task', 'legacy', 'Source', 'Edited', 'retail', ?, ?, ?, ?, ?, ?, ?, 'published', ?, ?)",
                           (encode(card), encode(card), encode(rating), now, encode(card), encode(rating), now, now, now))
    db = Database(path)
    db.initialize()
    db.initialize()
    saved = Repository(db).get_task("legacy-task", "legacy")
    assert saved.confirmed_topic == saved.published_topic == "retail"
    assert saved.published_card.model_dump() == card
    assert saved.published_rating.model_dump() == rating
    assert saved.original_text == "Source"
    assert not saved.has_unconfirmed_changes
    with db.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
