from fastapi.testclient import TestClient

from app.main import create_app


def test_shell_and_catalog_assets_are_served_without_exposing_drafts(tmp_path):
    with TestClient(create_app(tmp_path / "ui.sqlite3")) as client:
        shell = client.get("/ui")
        assert shell.status_code == 200
        assert "text/html" in shell.headers["content-type"]
        assert 'id="page-catalog"' in shell.text
        for asset in ("styles.css", "shell.js", "catalog.css", "catalog.js", "icons.svg",
                      "builder.css", "builder.js", "task-detail.css", "task-detail.js",
                      "proposal-form.css", "proposal-form.js"):
            assert f'/static/{asset}' in shell.text
            assert client.get(f"/static/{asset}").status_code == 200
        fixtures = client.get("/static/catalog-demo.json").json()
        assert len(fixtures) == 5
        assert {item["published_rating"]["level"] for item in fixtures} == {
            "draft", "working", "ready", "priority"
        }
        assert all(item["status"] == "published" for item in fixtures)
        assert client.get("/api/tasks").status_code == 400
        assert client.get("/").json()["service"] == "AI Sana Challenge Hub"
