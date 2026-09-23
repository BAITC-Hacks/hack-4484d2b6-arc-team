import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def database_path() -> Path:
    load_dotenv(ROOT / ".env", override=False)
    path = Path(os.getenv("DATABASE_PATH", "data/challenge_hub.sqlite3"))
    return path if path.is_absolute() else ROOT / path


def cors_origins() -> list[str]:
    load_dotenv(ROOT / ".env", override=False)
    return [s.strip() for s in os.getenv("CORS_ORIGINS", "").split(",") if s.strip()]
