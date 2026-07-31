"""Accessor for the chat_messages table.

Writes are not committed here; the caller owns the transaction (`with conn:`).
"""

import json
import sqlite3

from .common import DEFAULT_USER_ID, new_id, now_iso

_COLUMNS = "id, role, content, actions, created_at"


def append(
    conn: sqlite3.Connection, role: str, content: str, actions: dict | None = None
) -> dict:
    """Record a chat message and return the new row with actions parsed."""
    message_id = new_id()
    conn.execute(
        """
        INSERT INTO chat_messages (id, user_id, role, content, actions, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            message_id,
            DEFAULT_USER_ID,
            role,
            content,
            json.dumps(actions) if actions is not None else None,
            now_iso(),
        ),
    )
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM chat_messages WHERE id = ?", (message_id,)
    ).fetchone()
    return _to_dict(row)


def list_recent(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """The most recent messages, oldest first, with actions parsed."""
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM chat_messages WHERE user_id = ? ORDER BY rowid DESC LIMIT ?",
        (DEFAULT_USER_ID, limit),
    ).fetchall()
    return [_to_dict(row) for row in reversed(rows)]


def _to_dict(row: sqlite3.Row) -> dict:
    """Convert a message row to a dict, decoding the actions JSON."""
    message = dict(row)
    message["actions"] = json.loads(message["actions"]) if message["actions"] else None
    return message
