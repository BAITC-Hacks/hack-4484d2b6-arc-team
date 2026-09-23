"""Idempotent synthetic profiles and source drafts. Run: python seed.py."""
import argparse
import json
from pathlib import Path

from app.config import ROOT, database_path
from app.db import Database
from app.models import BusinessProfile, DraftCreate, Team
from app.repository import encode, utc_now
from app.models import TaskCard


def seed_database(db: Database, source: Path | None = None) -> dict[str, int]:
    data = json.loads((source or ROOT / "fixtures" / "demo.json").read_text(encoding="utf-8"))
    businesses = [BusinessProfile.model_validate(item) for item in data["businesses"]]
    teams = [Team.model_validate(item) for item in data["teams"]]
    drafts = [(item["id"], item["business_id"], DraftCreate.model_validate({k: v for k, v in item.items() if k not in {"id", "business_id"}})) for item in data["drafts"]]
    db.initialize()
    counts = {"businesses": 0, "teams": 0, "drafts": 0}
    with db.connect() as connection:
        for item in businesses:
            counts["businesses"] += connection.execute("INSERT INTO business_profiles VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING", (item.id, item.name, item.industry, item.contact, item.is_demo)).rowcount
        for item in teams:
            counts["teams"] += connection.execute("INSERT INTO teams VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING", (item.id, item.name, encode(item.interests), encode(item.skills), encode(item.technologies), item.is_demo)).rowcount
        for task_id, business_id, item in drafts:
            now = utc_now()
            counts["drafts"] += connection.execute("INSERT INTO tasks (id, business_id, original_text, draft_text, topic, proposed_card, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING", (task_id, business_id, item.original_text, item.original_text, item.topic, encode(TaskCard().model_dump()), now, now)).rowcount
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, help="Optional explicit SQLite file")
    parser.add_argument("--source", type=Path, help="Optional JSON in fixtures/demo.json format")
    args = parser.parse_args()
    db = Database(args.database.resolve() if args.database else database_path())
    print(json.dumps({"database": str(db.path), "inserted": seed_database(db, args.source)}, ensure_ascii=False))
