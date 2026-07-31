"""Accessor for the user_profile table.

Writes are not committed here; the caller owns the transaction (`with conn:`).
"""

import sqlite3

from .common import DEFAULT_USER_ID


def get(conn: sqlite3.Connection) -> dict:
    """The user profile as {"id", "cash_balance", "created_at"}."""
    row = conn.execute(
        "SELECT id, cash_balance, created_at FROM user_profile WHERE id = ?",
        (DEFAULT_USER_ID,),
    ).fetchone()
    return dict(row)


def set_cash(conn: sqlite3.Connection, cash: float) -> None:
    """Overwrite the cash balance."""
    conn.execute(
        "UPDATE user_profile SET cash_balance = ? WHERE id = ?",
        (cash, DEFAULT_USER_ID),
    )
