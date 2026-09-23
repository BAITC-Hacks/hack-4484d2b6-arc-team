import json
from datetime import datetime, timezone
from uuid import uuid4

from app.db import Database
from app.models import DemoProfiles, DraftCreate, DraftUpdate, Task, TaskCard

JSON_FIELDS = {"questions", "answers", "proposed_card", "confirmed_card", "confirmed_rating", "published_card", "published_rating"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def decode_task(row) -> Task:
    data = dict(row)
    for field in JSON_FIELDS:
        if data[field] is not None:
            data[field] = json.loads(data[field])
    return Task.model_validate(data)


class Repository:
    def __init__(self, db: Database):
        self.db = db

    def profiles(self) -> DemoProfiles:
        with self.db.connect() as connection:
            businesses = [dict(row) for row in connection.execute("SELECT * FROM business_profiles ORDER BY id")]
            teams = [dict(row) for row in connection.execute("SELECT * FROM teams ORDER BY id")]
        for team in teams:
            for key in ("interests", "skills", "technologies"):
                team[key] = json.loads(team[key])
        return DemoProfiles(businesses=businesses, teams=teams)

    def business_exists(self, business_id: str) -> bool:
        with self.db.connect() as connection:
            return connection.execute("SELECT 1 FROM business_profiles WHERE id = ?", (business_id,)).fetchone() is not None

    def create_draft(self, business_id: str, draft: DraftCreate, *, task_id: str | None = None) -> Task:
        task_id = task_id or str(uuid4())
        now = utc_now()
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO tasks (id, business_id, original_text, draft_text, topic, proposed_card, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (task_id, business_id, draft.original_text, draft.original_text, draft.topic, encode(TaskCard().model_dump()), now, now),
            )
            return decode_task(connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())

    def list_tasks(self, business_id: str) -> list[Task]:
        with self.db.connect() as connection:
            return [decode_task(row) for row in connection.execute("SELECT * FROM tasks WHERE business_id = ? ORDER BY created_at, id", (business_id,))]

    def get_task(self, task_id: str, business_id: str) -> Task | None:
        with self.db.connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ? AND business_id = ?", (task_id, business_id)).fetchone()
            return decode_task(row) if row else None

    def update_draft(self, task_id: str, business_id: str, update: DraftUpdate) -> Task | None:
        # Field names only come from the validated, extra-forbid DraftUpdate model.
        values = update.model_dump(mode="json", exclude_unset=True)
        for field in ("answers", "proposed_card"):
            if field in values:
                values[field] = encode(values[field])
        values["updated_at"] = utc_now()
        assignments = ", ".join(f"{field} = ?" for field in values)
        with self.db.connect() as connection:
            cursor = connection.execute(f"UPDATE tasks SET {assignments} WHERE id = ? AND business_id = ?", (*values.values(), task_id, business_id))
            if not cursor.rowcount:
                return None
            return decode_task(connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())
