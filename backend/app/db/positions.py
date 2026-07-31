"""Accessor for the positions table.

Writes are not committed here; the caller owns the transaction (`with conn:`).
"""

import sqlite3

from .common import DEFAULT_USER_ID, new_id, now_iso

_COLUMNS = "ticker, quantity, avg_cost, updated_at"


def list_all(conn: sqlite3.Connection) -> list[dict]:
    """All open positions, ordered by ticker."""
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM positions WHERE user_id = ? ORDER BY ticker",
        (DEFAULT_USER_ID,),
    ).fetchall()
    return [dict(row) for row in rows]


def get(conn: sqlite3.Connection, ticker: str) -> dict | None:
    """The position in ticker, or None if none is held."""
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM positions WHERE user_id = ? AND ticker = ?",
        (DEFAULT_USER_ID, ticker),
    ).fetchone()
    return dict(row) if row else None


def upsert(conn: sqlite3.Connection, ticker: str, quantity: float, avg_cost: float) -> dict:
    """Insert or replace the position in ticker and return it."""
    conn.execute(
        """
        INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (user_id, ticker) DO UPDATE SET
            quantity = excluded.quantity,
            avg_cost = excluded.avg_cost,
            updated_at = excluded.updated_at
        """,
        (new_id(), DEFAULT_USER_ID, ticker, quantity, avg_cost, now_iso()),
    )
    return get(conn, ticker)


def delete(conn: sqlite3.Connection, ticker: str) -> bool:
    """Delete the position in ticker. False if none was held."""
    cursor = conn.execute(
        "DELETE FROM positions WHERE user_id = ? AND ticker = ?",
        (DEFAULT_USER_ID, ticker),
    )
    return cursor.rowcount > 0
