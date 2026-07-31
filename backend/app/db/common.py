"""Shared helpers for the database layer."""

import uuid
from datetime import UTC, datetime

DEFAULT_USER_ID = "default"


def now_iso() -> str:
    """Current UTC time as an ISO 8601 string."""
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    """Fresh UUID4 primary key."""
    return str(uuid.uuid4())
