import json
from datetime import datetime, timezone
from uuid import uuid4

from app.db import Database
from app.models import AIMetadata, DemoProfiles, DraftCreate, DraftUpdate, Question, Task, TaskCard
from app.scoring import calculate_rating, is_filled

JSON_FIELDS = {"questions", "answers", "proposed_card", "confirmed_card", "confirmed_rating", "published_card", "published_rating", "questions_ai", "card_ai"}


class StaleTaskError(Exception):
    """The task changed after the version reviewed by the caller."""


class TaskStateError(Exception):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


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
        if "proposed_card" in values:
            values["card_ai"] = None
        values["updated_at"] = utc_now()
        assignments = ", ".join(f"{field} = ?" for field in values)
        with self.db.connect() as connection:
            cursor = connection.execute(f"UPDATE tasks SET {assignments} WHERE id = ? AND business_id = ?", (*values.values(), task_id, business_id))
            if not cursor.rowcount:
                return None
            return decode_task(connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())

    def _save_ai_fields(self, snapshot: Task, values: dict) -> Task:
        values = {field: encode(value) for field, value in values.items()}
        values["updated_at"] = utc_now()
        assignments = ", ".join(f"{field} = ?" for field in values)
        with self.db.connect() as connection:
            cursor = connection.execute(
                f"UPDATE tasks SET {assignments} WHERE id = ? AND business_id = ? AND updated_at = ?",
                (*values.values(), snapshot.id, snapshot.business_id, snapshot.updated_at.isoformat()),
            )
            if not cursor.rowcount:
                raise StaleTaskError()
            return decode_task(connection.execute("SELECT * FROM tasks WHERE id = ?", (snapshot.id,)).fetchone())

    def save_questions(self, snapshot: Task, questions: list[Question], meta: AIMetadata) -> Task:
        # Keep answered questions and their IDs; regeneration must not orphan answers.
        answered = {q.id: q for q in snapshot.questions if snapshot.answers.get(q.id, "").strip()}
        merged = {q.id: answered.get(q.id, q) for q in questions}
        merged.update(answered)
        return self._save_ai_fields(snapshot, {
            "questions": [q.model_dump() for q in merged.values()],
            "questions_ai": meta.model_dump(mode="json"),
        })

    def save_answers(self, snapshot: Task, answers: dict[str, str]) -> Task:
        return self._save_ai_fields(snapshot, {"answers": {**snapshot.answers, **answers}})

    def save_generated_card(self, snapshot: Task, card: TaskCard, meta: AIMetadata) -> Task:
        return self._save_ai_fields(snapshot, {
            "proposed_card": card.model_dump(), "card_ai": meta.model_dump(mode="json"),
        })

    def confirm_task(self, task_id: str, business_id: str, expected_updated_at: datetime,
                     proposed_card: TaskCard | None = None) -> Task | None:
        with self.db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM tasks WHERE id=? AND business_id=?", (task_id, business_id)).fetchone()
            if row is None:
                return None
            task = decode_task(row)
            if task.updated_at != expected_updated_at:
                raise StaleTaskError()
            card = proposed_card if proposed_card is not None else task.proposed_card
            if not is_filled(card.title):
                raise TaskStateError("Укажите название задачи перед подтверждением", 422)
            rating = calculate_rating(card)
            if task.confirmed_card == card and task.confirmed_rating == rating and task.confirmed_topic == task.topic and task.proposed_card == card:
                return task
            now = utc_now()
            # Rating is derived here, not accepted from the client or AI.
            connection.execute(
                "UPDATE tasks SET proposed_card=?, confirmed_card=?, confirmed_rating=?, confirmed_topic=?, confirmed_at=?, updated_at=?, card_ai=? WHERE id=?",
                (encode(card.model_dump()), encode(card.model_dump()), encode(rating.model_dump()), task.topic, now, now,
                 row["card_ai"] if task.proposed_card == card else None, task_id),
            )
            return decode_task(connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())

    def publish_task(self, task_id: str, business_id: str, expected_updated_at: datetime) -> Task | None:
        with self.db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM tasks WHERE id=? AND business_id=?", (task_id, business_id)).fetchone()
            if row is None:
                return None
            task = decode_task(row)
            if task.updated_at != expected_updated_at:
                raise StaleTaskError()
            if task.confirmed_card is None or task.confirmed_rating is None:
                raise TaskStateError("Сначала подтвердите карточку задачи")
            if task.has_unconfirmed_changes:
                raise TaskStateError("Подтвердите изменения карточки и темы перед публикацией")
            if task.status == "published" and not task.has_unpublished_changes:
                return task
            now = utc_now()
            # No minimum score: a confirmed title-only card can publish at 0/100.
            connection.execute(
                "UPDATE tasks SET status='published', published_card=?, published_rating=?, published_topic=?, published_at=?, updated_at=? WHERE id=?",
                (row["confirmed_card"], row["confirmed_rating"], task.confirmed_topic,
                 row["published_at"] or now, now, task_id),
            )
            return decode_task(connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
