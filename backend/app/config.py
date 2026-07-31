"""Environment configuration for the FinAlly backend.

The project-root `.env` is loaded once at import so anything reading
`os.environ` afterwards (the market data factory, the LLM client) sees it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent

load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    """Resolved runtime configuration."""

    db_path: str
    static_dir: Path
    snapshot_interval: float
    massive_api_key: str
    openrouter_api_key: str
    llm_mock: bool


def get_settings() -> Settings:
    """Read configuration from the environment.

    Called per app creation rather than cached at import, so tests can set
    environment variables before building an app.
    """
    return Settings(
        db_path=os.environ.get("DB_PATH", str(PROJECT_ROOT / "db" / "finally.db")),
        static_dir=Path(os.environ.get("STATIC_DIR", str(BACKEND_DIR / "static"))),
        snapshot_interval=float(os.environ.get("SNAPSHOT_INTERVAL", "30.0")),
        massive_api_key=os.environ.get("MASSIVE_API_KEY", "").strip(),
        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY", "").strip(),
        llm_mock=os.environ.get("LLM_MOCK", "").strip().lower() == "true",
    )
