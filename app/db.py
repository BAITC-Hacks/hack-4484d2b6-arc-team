import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class Database:
    """Short-lived connections; each write context is one transaction."""

    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError("Database schema is newer than this application")
            if version == 0:
                schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
                connection.executescript("BEGIN IMMEDIATE;\n" + schema + "\nPRAGMA user_version = 1;\nCOMMIT;")


if __name__ == "__main__":
    from app.config import database_path

    db = Database(database_path())
    db.initialize()
    print(f"Database initialized: {db.path}")
