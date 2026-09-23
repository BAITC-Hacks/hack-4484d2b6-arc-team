"""Completed team steps share one database and preserve publication boundaries."""
from fastapi.testclient import TestClient

from app.ai import AIService
from app.config import AISettings
from app.db import Database
from app.main import create_app
from seed import seed_database


def test_constructor_to_publication_and_later_edits_survive_restart(tmp_path):
    path = tmp_path / "integrated.sqlite3"
    seed_database(Database(path))
    owner = {"X-Demo-Business-Id": "business-1"}
    ai = AIService(AISettings(mode="local", api_key=""))

    with TestClient(create_app(path, ai)) as client:
        response = client.post("/api/tasks", headers=owner, json={
            "original_text": "Хотим сократить опоздания доставки.", "topic": "logistics",
        })
        assert response.status_code == 201
        url = f'/api/tasks/{response.json()["id"]}'
        response = client.post(f"{url}/questions", headers=owner, json={"mode": "local"})
        assert response.status_code == 200
        questions = response.json()["task"]["questions"]
        assert len(questions) >= 3
        answers_by_field = {
            "data": "Обезличенный CSV с историей заказов",
            "expected_result": "Прототип панели диспетчера",
        }
        answers = {q["id"]: answers_by_field.get(q["field"], "не знаю") for q in questions}
        response = client.post(f"{url}/generate-card", headers=owner,
                               json={"mode": "local", "answers": answers})
        assert response.status_code == 200
        generated = response.json()["task"]
        assert generated["answers"] == answers
        assert generated["confirmed_rating"] is None
        assert generated["published_card"] is None
        assert generated["proposed_card"]["success_criteria"] == ""

        card = generated["proposed_card"]
        card["title"] = "Ручная правка: диспетчер доставки"
        response = client.patch(url, headers=owner, json={"proposed_card": card})
        assert response.status_code == 200
        saved = response.json()
        assert saved["card_ai"] is None
        response = client.post(f"{url}/confirm", headers=owner,
                               json={"expected_updated_at": saved["updated_at"]})
        assert response.status_code == 200
        confirmed = response.json()
        assert confirmed["confirmed_card"] == card
        assert confirmed["confirmed_rating"]["score"] > 0
        assert "success_criteria" in confirmed["confirmed_rating"]["missing_fields"]
        response = client.post(f"{url}/publish", headers=owner,
                               json={"expected_updated_at": confirmed["updated_at"]})
        assert response.status_code == 200
        published = response.json()

        # Subsequent constructor saves and AI requests cannot silently republish.
        response = client.patch(url, headers=owner, json={
            "draft_text": "Нужно подготовить другой учебный прототип.", "topic": "education",
        })
        assert response.status_code == 200
        response = client.post(f"{url}/questions", headers=owner, json={"mode": "local"})
        assert response.status_code == 200
        response = client.post(f"{url}/generate-card", headers=owner, json={"mode": "local"})
        assert response.status_code == 200
        edited = response.json()["task"]
        assert edited["has_unconfirmed_changes"]
        assert edited["published_card"] == published["published_card"]
        assert edited["published_rating"] == published["published_rating"]
        assert edited["published_topic"] == "logistics"
        assert client.post(f"{url}/publish", headers=owner,
                           json={"expected_updated_at": edited["updated_at"]}).status_code == 409
        assert client.get(url, headers={"X-Demo-Business-Id": "business-2"}).status_code == 404

    with TestClient(create_app(path, ai)) as restarted:
        assert restarted.get(url, headers=owner).json() == edited
