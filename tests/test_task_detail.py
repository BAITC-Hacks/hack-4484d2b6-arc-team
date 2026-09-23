from fastapi.testclient import TestClient

from app.main import create_app
from app.models import TaskCard


def test_detail_fixtures_use_public_card_contract_and_cover_missing_fields(tmp_path):
    with TestClient(create_app(tmp_path / "detail.sqlite3")) as client:
        tasks = client.get("/static/catalog-demo.json").json()
        required = set(TaskCard.model_fields)
        for task in tasks:
            assert task["status"] == "published"
            assert required <= set(task["published_card"])
            card = TaskCard.model_validate(task["published_card"])
            assert card.title and card.need
            assert "proposed_card" not in task
        incomplete = next(task for task in tasks if task["id"] == "preview-education")
        assert incomplete["published_card"]["success_criteria"] == ""
        assert incomplete["published_rating"]["score"] < 40
        shell = client.get("/ui").text
        assert shell.index('src="/static/proposal-form.js"') < shell.index('src="/static/task-detail.js"')
        assert shell.index('src="/static/task-detail.js"') < shell.index('src="/static/shell.js"')
        assert 'id="catalog-preview"' not in shell
        assert client.get("/static/task-detail.js").status_code == 200
        assert client.get("/static/task-detail.css").status_code == 200
