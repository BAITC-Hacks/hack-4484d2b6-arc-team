import os
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class AISettings:
    mode: str = "local"
    api_key: str = field(default="", repr=False)
    model: str = "gpt-4o-mini"
    timeout_seconds: float = 20.0

    def __post_init__(self):
        if self.mode not in {"local", "openai"}:
            raise ValueError("AI_MODE must be local or openai")
        if not 1 <= self.timeout_seconds <= 60:
            raise ValueError("AI_TIMEOUT_SECONDS must be between 1 and 60")


def ai_settings() -> AISettings:
    load_dotenv(ROOT / ".env", override=False)
    return AISettings(
        mode=os.getenv("AI_MODE", "local"),
        api_key=os.getenv("OPENAI_API_KEY", ""),
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        timeout_seconds=float(os.getenv("AI_TIMEOUT_SECONDS", "20")),
    )
