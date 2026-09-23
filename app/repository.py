import json
from datetime import datetime, timezone
from uuid import uuid4

from app.db import Database
from app.models import (AIMetadata, DemoProfiles, DraftCreate, DraftUpdate, Milestone, MilestoneCreate,
                        ProposalCreate, ProposalView, PublishedTask, Question, Task, TaskCard, LeaderboardTeam)
from app.scoring import calculate_rating, is_filled

JSON_FIELDS = {"questions", "answers", "proposed_card", "confirmed_card", "confirmed_rating", "published_card", "published_rating", "questions_ai", "card_ai"}
MILESTONE_POINTS = 10
PUBLIC_TASK_SQL = """SELECT id, published_topic AS topic, status, published_at,
                     published_card, published_rating FROM tasks WHERE status='published'"""
PROPOSAL_SQL = """SELECT p.*, teams.name AS team_name,
                  json_extract(tasks.published_card, '$.title') AS task_title
                  FROM proposals p JOIN teams ON teams.id=p.team_id
                  JOIN tasks ON tasks.id=p.task_id"""


class StaleTaskError(Exception):
    """The task changed after the version reviewed by the caller."""


class TaskStateError(Exception):
    def __init__(self, message: str, status_code: int = 409, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code or ("validation_error" if status_code == 422 else "confirmation_required")


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


def decode_public_task(row) -> PublishedTask:
    data = dict(row)
    for field in ("published_card", "published_rating"):
        data[field] = json.loads(data[field])
    return PublishedTask.model_validate(data)


def proposal_view(connection, row) -> ProposalView:
    # ponytail: one milestone query per proposal; batch this for a large production catalog.
    milestones = [dict(item) for item in connection.execute(
        "SELECT * FROM milestones WHERE proposal_id=? ORDER BY created_at, id", (row["id"],))]
    return ProposalView.model_validate({**dict(row), "milestones": milestones})


class Repository:
    def __init__(self, db: Database):
        self.db = db

    def profiles(self) -> DemoProfiles:
        with self.db.connect() as connection:
            businesses = [dict(row) for row in connection.execute("SELECT * FROM business_profiles ORDER BY id")]
            teams = [dict(row) for row in connection.execute("""
                SELECT teams.*, COALESCE(SUM(m.points_awarded), 0) AS points FROM teams
                LEFT JOIN proposals p ON p.team_id=teams.id
                LEFT JOIN milestones m ON m.proposal_id=p.id AND m.status='confirmed'
                GROUP BY teams.id ORDER BY teams.id
            """)]
        for team in teams:
            for key in ("interests", "skills", "technologies"):
                team[key] = json.loads(team[key])
        return DemoProfiles(businesses=businesses, teams=teams)

    def business_exists(self, business_id: str) -> bool:
        with self.db.connect() as connection:
            return connection.execute("SELECT 1 FROM business_profiles WHERE id = ?", (business_id,)).fetchone() is not None

    def leaderboard(self) -> list[LeaderboardTeam]:
        # Derive everything from the confirmed ledger; no second balance to synchronise.
        with self.db.connect() as connection:
            rows = connection.execute("""
                SELECT t.id AS team_id, t.name,
                       COUNT(DISTINCT CASE WHEN m.id IS NOT NULL THEN p.task_id END) AS completed_tasks,
                       COUNT(m.id) AS confirmed_milestones,
                       COUNT(DISTINCT CASE WHEN m.id IS NOT NULL THEN task.business_id END) AS businesses,
                       COALESCE(SUM(m.points_awarded), 0) AS points
                FROM teams t
                LEFT JOIN proposals p ON p.team_id=t.id
                LEFT JOIN tasks task ON task.id=p.task_id
                LEFT JOIN milestones m ON m.proposal_id=p.id AND m.status='confirmed'
                GROUP BY t.id ORDER BY completed_tasks DESC, t.id
            """).fetchall()
        result = []
        previous = None
        rank = 1
        for position, row in enumerate(rows, 1):
            data = dict(row)
            if data['completed_tasks'] != previous:
                rank = position
            previous = data['completed_tasks']
            rules = (
                ('first_result', 'Первый результат', 'Бизнес подтвердил первый этап.', data['confirmed_milestones'], 1),
                ('three_results', 'Довели до результата', 'Бизнес подтвердил три этапа.', data['confirmed_milestones'], 3),
                ('different_businesses', 'Разный опыт', 'Есть подтверждённые этапы для двух разных бизнесов.', data['businesses'], 2),
            )
            achievements = [dict(id=key, title=title, description=description,
                                 progress=min(progress, target), target=target, earned=progress >= target)
                            for key, title, description, progress, target in rules]
            result.append(LeaderboardTeam(**data, rank=rank, achievements=achievements))
        return result

    def team_exists(self, team_id: str) -> bool:
        with self.db.connect() as connection:
            return connection.execute("SELECT 1 FROM teams WHERE id=?", (team_id,)).fetchone() is not None

    def catalog(self, topic: str | None = None, readiness: str | None = None) -> list[PublishedTask]:
        sql, params = PUBLIC_TASK_SQL, []
        if topic is not None:
            sql += " AND published_topic=?"
            params.append(topic)
        if readiness is not None:
            sql += " AND json_extract(published_rating, '$.level')=?"
            params.append(readiness)
        sql += " ORDER BY json_extract(published_rating, '$.score') DESC, published_at, id"
        with self.db.connect() as connection:
            return [decode_public_task(row) for row in connection.execute(sql, params)]

    def public_task(self, task_id: str) -> PublishedTask | None:
        with self.db.connect() as connection:
            row = connection.execute(PUBLIC_TASK_SQL + " AND id=?", (task_id,)).fetchone()
            return decode_public_task(row) if row else None

    def create_proposal(self, task_id: str, team_id: str, payload: ProposalCreate) -> ProposalView:
        values = payload.model_dump(mode="json")
        with self.db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not connection.execute("SELECT 1 FROM tasks WHERE id=? AND status='published'", (task_id,)).fetchone():
                raise TaskStateError("Опубликованная задача не найдена", 404, "not_found")
            existing = connection.execute(PROPOSAL_SQL + " WHERE p.task_id=? AND p.team_id=?", (task_id, team_id)).fetchone()
            if existing:
                if any(existing[key] != value for key, value in values.items()):
                    raise TaskStateError("Команда уже отправила предложение по этой задаче", code="proposal_exists")
                return proposal_view(connection, existing)
            proposal_id = str(uuid4())
            connection.execute("""INSERT INTO proposals
                (id, task_id, team_id, idea, plan, timeline, prototype_url, questions, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (proposal_id, task_id, team_id, values["idea"], values["plan"], values["timeline"],
                 values["prototype_url"], values["questions"], utc_now()))
            return proposal_view(connection, connection.execute(PROPOSAL_SQL + " WHERE p.id=?", (proposal_id,)).fetchone())

    def task_proposals(self, task_id: str, business_id: str) -> list[ProposalView] | None:
        with self.db.connect() as connection:
            if not connection.execute("SELECT 1 FROM tasks WHERE id=? AND business_id=?", (task_id, business_id)).fetchone():
                return None
            return [proposal_view(connection, row) for row in connection.execute(
                PROPOSAL_SQL + " WHERE p.task_id=? ORDER BY p.created_at, p.id", (task_id,))]

    def team_proposals(self, team_id: str) -> list[ProposalView]:
        with self.db.connect() as connection:
            return [proposal_view(connection, row) for row in connection.execute(
                PROPOSAL_SQL + " WHERE p.team_id=? ORDER BY p.created_at, p.id", (team_id,))]

    def decide_proposal(self, proposal_id: str, business_id: str, status: str) -> ProposalView:
        with self.db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(PROPOSAL_SQL + " WHERE p.id=? AND tasks.business_id=?",
                                     (proposal_id, business_id)).fetchone()
            if row is None:
                raise TaskStateError("Предложение не найдено", 404, "not_found")
            if row["status"] == status:
                return proposal_view(connection, row)
            if row["status"] != "submitted":
                raise TaskStateError("По предложению уже принято другое решение", code="decision_conflict")
            connection.execute("UPDATE proposals SET status=?, decided_at=? WHERE id=?", (status, utc_now(), proposal_id))
            return proposal_view(connection, connection.execute(PROPOSAL_SQL + " WHERE p.id=?", (proposal_id,)).fetchone())

    def submit_milestone(self, proposal_id: str, team_id: str, payload: MilestoneCreate) -> Milestone:
        values = payload.model_dump(mode="json")
        with self.db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            proposal = connection.execute("SELECT * FROM proposals WHERE id=? AND team_id=?", (proposal_id, team_id)).fetchone()
            if proposal is None:
                raise TaskStateError("Предложение не найдено", 404, "not_found")
            if proposal["status"] != "selected":
                raise TaskStateError("Отправить результат может только выбранная команда", code="team_not_selected")
            existing = connection.execute("""SELECT * FROM milestones WHERE proposal_id=?
                AND description=? AND result_url IS ? ORDER BY created_at, id LIMIT 1""",
                (proposal_id, values["description"], values["result_url"])).fetchone()
            if existing:
                return Milestone.model_validate(dict(existing))
            milestone_id = str(uuid4())
            connection.execute("INSERT INTO milestones (id, proposal_id, description, result_url, created_at) VALUES (?, ?, ?, ?, ?)",
                               (milestone_id, proposal_id, values["description"], values["result_url"], utc_now()))
            return Milestone.model_validate(dict(connection.execute("SELECT * FROM milestones WHERE id=?", (milestone_id,)).fetchone()))

    def confirm_milestone(self, milestone_id: str, business_id: str) -> Milestone:
        with self.db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("""SELECT m.* FROM milestones m
                JOIN proposals p ON p.id=m.proposal_id JOIN tasks t ON t.id=p.task_id
                WHERE m.id=? AND t.business_id=?""", (milestone_id, business_id)).fetchone()
            if row is None:
                raise TaskStateError("Этап не найден", 404, "not_found")
            proposal = connection.execute("SELECT status FROM proposals WHERE id=?", (row["proposal_id"],)).fetchone()
            if proposal["status"] != "selected":
                raise TaskStateError("Команда не выбрана для этой задачи", code="team_not_selected")
            if row["status"] != "confirmed":
                connection.execute("UPDATE milestones SET status='confirmed', points_awarded=?, confirmed_at=? WHERE id=?",
                                   (MILESTONE_POINTS, utc_now(), milestone_id))
            return Milestone.model_validate(dict(connection.execute("SELECT * FROM milestones WHERE id=?", (milestone_id,)).fetchone()))

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
