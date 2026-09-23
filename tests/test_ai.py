import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.ai import AIService, OpenAIProvider
from app.config import AISettings
from app.db import Database
from app.main import create_app
from app.models import DraftUpdate, TaskCard
from app.repository import Repository, encode, utc_now
from seed import seed_database

OWNER = {"X-Demo-Business-Id": "business-1"}
OTHER = {"X-Demo-Business-Id": "business-2"}
QUESTIONS = {"questions": [
    {"field": "data", "text": "Какие данные об остатках доступны?"},
    {"field": "expected_result", "text": "Что команда должна передать магазину?"},
    {"field": "success_criteria", "text": "Как вы проверите учёт остатков?"},
]}


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "ai.sqlite3")
    seed_database(database)
    return database


def client_for(db, handler=None, *, key="test-key", timeout=2):
    settings = AISettings(mode="local", api_key=key, timeout_seconds=timeout)
    provider = OpenAIProvider(settings, httpx.MockTransport(handler)) if handler else None
    return TestClient(create_app(db.path, AIService(settings, provider)))


def envelope(payload):
    return {"status": "completed", "output": [{"type": "message", "content": [
        {"type": "output_text", "text": json.dumps(payload, ensure_ascii=False)}
    ]}]}


def ask(client, mode="local", task_id="draft-1"):
    return client.post(f"/api/tasks/{task_id}/questions", headers=OWNER, json={"mode": mode})


def generate(client, mode="local", answers=None, task_id="draft-1"):
    body = {"mode": mode}
    if answers is not None:
        body["answers"] = answers
    return client.post(f"/api/tasks/{task_id}/generate-card", headers=OWNER, json=body)


def test_local_end_to_end_and_metadata_survive_restart(db):
    with client_for(db) as client:
        questions = ask(client).json()
        assert questions["ai"]["mode"] == "local"
        assert "без внешней" in questions["ai"]["message"]
        assert len(questions["task"]["questions"]) >= 3
        assert all("остатки товаров" in q["text"] for q in questions["task"]["questions"])
        answers = {"q-data": "Есть CSV на 500 товаров.", "q-expected_result": "Таблица остатков.", "q-success_criteria": "Все товары с остатком ниже 5 найдены.", "q-users": "Не знаю"}
        result = generate(client, answers=answers)
        assert result.status_code == 200
        task = result.json()["task"]
        assert task["proposed_card"]["data"] == answers["q-data"]
        assert task["proposed_card"]["users"] == ""
        assert task["proposed_card"]["contact"] == ""
        assert task["confirmed_card"] is None
        assert task["published_card"] is None
        assert task["confirmed_rating"] is None
        assert task["status"] == "draft"
    with client_for(db) as client:
        stored = client.get("/api/tasks/draft-1", headers=OWNER).json()
        assert stored == task
        assert stored["card_ai"]["mode"] == "local"
        assert stored["answers"] == answers


def test_openai_request_schema_and_valid_response(db):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        assert request.url == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"] == "Bearer test-key"
        data = requests[-1]
        assert data["store"] is False
        assert data["text"]["format"]["strict"] is True
        assert "draft_text" in json.loads(data["input"])
        assert "original_text" not in json.loads(data["input"])
        schema = data["text"]["format"]["schema"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        if data["text"]["format"]["name"] == "task_questions":
            return httpx.Response(200, json=envelope(QUESTIONS))
        card = TaskCard(title="остатки товаров", data="Есть CSV.").model_dump()
        return httpx.Response(200, json=envelope({"card": card}))

    with client_for(db, handler) as client:
        result = ask(client, "openai")
        assert result.status_code == 200
        assert result.json()["task"]["questions"][0]["id"] == "q-data"
        result = generate(client, "openai", {"q-data": "Есть CSV."})
        assert result.status_code == 200
        assert result.json()["task"]["proposed_card"]["data"] == "Есть CSV."
        assert result.json()["ai"]["model"] == "gpt-4o-mini"
        assert len(requests) == 2


@pytest.mark.parametrize("payload", [
    {"questions": QUESTIONS["questions"][:2]},
    {"questions": [QUESTIONS["questions"][0]] * 3},
    {"questions": [*QUESTIONS["questions"][:2], {"field": "score", "text": "Назначить баллы?"}]},
    {"questions": QUESTIONS["questions"], "status": "published"},
    {"questions": [*QUESTIONS["questions"][:2], {"field": "users", "text": " "}]},
])
def test_bad_questions_do_not_replace_saved_questions_or_answers(db, payload):
    with client_for(db, lambda request: httpx.Response(200, json=envelope(payload))) as client:
        ask(client)
        generate(client, answers={"q-data": "CSV"})
        before = client.get("/api/tasks/draft-1", headers=OWNER).json()
        result = ask(client, "openai")
        assert result.status_code == 502
        assert result.json()["error"]["code"] == "ai_invalid_response"
        assert client.get("/api/tasks/draft-1", headers=OWNER).json() == before


@pytest.mark.parametrize("failure,expected", [
    ("timeout", (504, "ai_timeout")),
    ("network", (503, "ai_unavailable")),
    ("rate_limit", (503, "ai_unavailable")),
    ("invalid_json", (502, "ai_invalid_response")),
    ("truncated", (502, "ai_incomplete")),
    ("refusal", (502, "ai_refusal")),
])
def test_provider_failure_preserves_new_answers_and_old_card(db, failure, expected):
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("private provider detail")
        if failure == "network":
            raise httpx.ConnectError("private provider detail")
        if failure == "rate_limit":
            return httpx.Response(429, text="private provider detail")
        if failure == "invalid_json":
            return httpx.Response(200, text="not json")
        if failure == "truncated":
            return httpx.Response(200, json={"status": "incomplete", "output": []})
        return httpx.Response(200, json={"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "private provider detail"}]}]})

    with client_for(db, handler) as client:
        ask(client)
        before = generate(client, answers={"q-data": "Старая таблица"}).json()["task"]
        result = generate(client, "openai", {"q-data": "Новый CSV"})
        assert result.status_code == expected[0]
        assert result.json()["error"]["code"] == expected[1]
        assert "private provider detail" not in result.text
        saved = client.get("/api/tasks/draft-1", headers=OWNER).json()
        assert saved["answers"]["q-data"] == "Новый CSV"
        assert saved["proposed_card"] == before["proposed_card"]
        assert saved["card_ai"] == before["card_ai"]
        assert len(calls) == 1  # No hidden retry or automatic fake success.
        fallback = generate(client)
        assert fallback.status_code == 200
        assert fallback.json()["ai"]["mode"] == "local"
        assert fallback.json()["task"]["proposed_card"]["data"] == "Новый CSV"


@pytest.mark.parametrize("payload", [
    {"card": {"title": "Missing fields"}},
    {"card": {**TaskCard().model_dump(), "contact": "invented@example.com"}},
    {"card": {**TaskCard().model_dump(), "constraints": "Срок 2 недели, бюджет 100000"}},
    {"card": {**TaskCard().model_dump(), "score": 100}},
    {"card": {**TaskCard().model_dump(), "data": 123}},
])
def test_incomplete_or_invented_card_is_rejected(db, payload):
    with client_for(db, lambda request: httpx.Response(200, json=envelope(payload))) as client:
        ask(client)
        before = generate(client).json()["task"]
        result = generate(client, "openai")
        assert result.status_code == 502
        assert client.get("/api/tasks/draft-1", headers=OWNER).json() == before


def test_answered_questions_survive_regeneration(db):
    with client_for(db, lambda request: httpx.Response(200, json=envelope(QUESTIONS))) as client:
        first = ask(client).json()["task"]["questions"]
        generate(client, answers={"q-users": "Кладовщик"})
        regenerated = ask(client, "openai").json()["task"]
        assert regenerated["answers"]["q-users"] == "Кладовщик"
        assert next(q for q in regenerated["questions"] if q["id"] == "q-users") == next(q for q in first if q["id"] == "q-users")


def test_owner_checks_happen_before_provider_call(db):
    def unexpected(request):
        pytest.fail("Provider must not be called")

    with client_for(db, unexpected) as client:
        for path in ("questions", "generate-card"):
            assert client.post(f"/api/tasks/draft-1/{path}", headers=OTHER, json={"mode": "openai"}).status_code == 404
        assert generate(client).status_code == 409
        ask(client)
        assert generate(client, answers={"unknown-id": "value"}).status_code == 422


def test_missing_key_and_explicit_local_mode(db):
    with client_for(db, key="") as client:
        assert client.get("/api/ai/status").json()["openai_configured"] is False
        response = ask(client, "openai")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "ai_not_configured"
        assert ask(client).status_code == 200


def test_concurrent_edit_is_not_overwritten_by_ai(db):
    repo = Repository(db)

    def handler(request):
        repo.update_draft("draft-1", "business-1", DraftUpdate(draft_text="Новая правка пользователя"))
        return httpx.Response(200, json=envelope(QUESTIONS))

    with client_for(db, handler) as client:
        result = ask(client, "openai")
        assert result.status_code == 409
        assert result.json()["error"]["code"] == "task_changed"
        assert repo.get_task("draft-1", "business-1").draft_text == "Новая правка пользователя"
        assert repo.get_task("draft-1", "business-1").questions == []


def test_ai_never_changes_published_or_confirmed_snapshots(db):
    card = TaskCard(title="Подтверждено бизнесом").model_dump()
    rating = {"score": 0, "level": "draft", "categories": [], "missing_fields": []}
    with db.connect() as connection:
        connection.execute("UPDATE tasks SET confirmed_card=?, confirmed_rating=?, confirmed_at=?, published_card=?, published_rating=?, published_at=?, status='published' WHERE id='draft-1'",
                           (encode(card), encode(rating), utc_now(), encode(card), encode(rating), utc_now()))
    with client_for(db) as client:
        ask(client)
        task = generate(client, answers={"q-data": "Есть CSV"}).json()["task"]
        assert task["confirmed_card"] == task["published_card"] == card
        assert task["confirmed_rating"] == task["published_rating"] == rating
        assert task["status"] == "published"


def test_generated_text_is_not_recycled_as_user_evidence(db):
    with client_for(db) as client:
        ask(client)
        generated = generate(client).json()["task"]
        client.patch("/api/tasks/draft-1", headers=OWNER, json={"draft_text": "Теперь нужна другая задача"})
        regenerated = generate(client).json()["task"]
        assert regenerated["proposed_card"]["context"] == "Теперь нужна другая задача"
        assert regenerated["proposed_card"]["context"] != generated["proposed_card"]["context"]
        edited = client.patch("/api/tasks/draft-1", headers=OWNER, json={"proposed_card": {"title": "Ручная правка"}}).json()
        assert edited["card_ai"] is None
        assert generate(client).json()["task"]["proposed_card"]["title"] == "Ручная правка"


def test_version_one_database_migrates_without_losing_tasks(tmp_path):
    path = tmp_path / "v1.sqlite3"
    schema = Path(__file__).resolve().parents[1] / "app" / "schema.sql"
    with sqlite3.connect(path) as connection:
        connection.executescript(schema.read_text(encoding="utf-8"))
        connection.execute("PRAGMA user_version=1")
        connection.execute("INSERT INTO business_profiles VALUES ('legacy', 'Legacy', 'retail', '', 1)")
        connection.execute("INSERT INTO tasks (id, business_id, original_text, draft_text, proposed_card, created_at, updated_at) VALUES ('legacy-task', 'legacy', 'Source', 'Edited', ?, ?, ?)",
                           (encode(TaskCard().model_dump()), utc_now(), utc_now()))
    db = Database(path)
    db.initialize()
    db.initialize()
    saved = Repository(db).get_task("legacy-task", "legacy")
    assert saved.original_text == "Source"
    assert saved.draft_text == "Edited"
    assert saved.card_ai is None
    with db.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
