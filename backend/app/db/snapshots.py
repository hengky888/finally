"""Accessor for the portfolio_snapshots table (append-only).

Writes are not committed here; the caller owns the transaction (`with conn:`).
"""

import sqlite3

from .common import DEFAULT_USER_ID, new_id, now_iso

_COLUMNS = "id, total_value, recorded_at"


def append(conn: sqlite3.Connection, total_value: float) -> dict:
    """Record a portfolio value snapshot and return the new row."""
    snapshot_id = new_id()
    conn.execute(
        """
        INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at)
        VALUES (?, ?, ?, ?)
        """,
        (snapshot_id, DEFAULT_USER_ID, total_value, now_iso()),
    )
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM portfolio_snapshots WHERE id = ?", (snapshot_id,)
    ).fetchone()
    return dict(row)


def list_all(conn: sqlite3.Connection) -> list[dict]:
    """Every snapshot, oldest first."""
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM portfolio_snapshots WHERE user_id = ? ORDER BY rowid",
        (DEFAULT_USER_ID,),
    ).fetchall()
    return [dict(row) for row in rows]
