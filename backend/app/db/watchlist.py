"""Accessor for the watchlist table.

Writes are not committed here; the caller owns the transaction (`with conn:`).
"""

import sqlite3

from .common import DEFAULT_USER_ID, new_id, now_iso


def list_tickers(conn: sqlite3.Connection) -> list[str]:
    """Watched tickers in insertion order."""
    rows = conn.execute(
        "SELECT ticker FROM watchlist WHERE user_id = ? ORDER BY rowid",
        (DEFAULT_USER_ID,),
    ).fetchall()
    return [row["ticker"] for row in rows]


def add(conn: sqlite3.Connection, ticker: str) -> bool:
    """Add ticker to the watchlist. False if it was already present."""
    cursor = conn.execute(
        "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
        (new_id(), DEFAULT_USER_ID, ticker, now_iso()),
    )
    return cursor.rowcount > 0


def remove(conn: sqlite3.Connection, ticker: str) -> bool:
    """Remove ticker from the watchlist. False if it was absent."""
    cursor = conn.execute(
        "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?",
        (DEFAULT_USER_ID, ticker),
    )
    return cursor.rowcount > 0
