"""Accessor for the trades table (append-only).

Writes are not committed here; the caller owns the transaction (`with conn:`).
"""

import sqlite3

from .common import DEFAULT_USER_ID, new_id, now_iso

_COLUMNS = "id, ticker, side, quantity, price, executed_at"


def append(
    conn: sqlite3.Connection, ticker: str, side: str, quantity: float, price: float
) -> dict:
    """Record an executed trade and return the new row."""
    trade_id = new_id()
    conn.execute(
        """
        INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (trade_id, DEFAULT_USER_ID, ticker, side, quantity, price, now_iso()),
    )
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM trades WHERE id = ?", (trade_id,)
    ).fetchone()
    return dict(row)


def list_recent(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """The most recent trades, newest first."""
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM trades WHERE user_id = ? ORDER BY rowid DESC LIMIT ?",
        (DEFAULT_USER_ID, limit),
    ).fetchall()
    return [dict(row) for row in rows]
