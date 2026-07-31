"""Tests for schema creation, seeding and idempotency."""

import sqlite3

import pytest

from app.db import get_connection, init_db, profile, watchlist
from app.db.schema import DEFAULT_CASH_BALANCE, DEFAULT_TICKERS

TABLES = {
    "user_profile",
    "watchlist",
    "positions",
    "trades",
    "portfolio_snapshots",
    "chat_messages",
}


def table_names(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row["name"] for row in rows}


def test_creates_all_tables(conn):
    assert TABLES <= table_names(conn)


def test_profile_table_is_singular(conn):
    assert "users_profile" not in table_names(conn)


def test_creates_missing_parent_directory(tmp_path):
    init_db(str(tmp_path / "nested" / "dir" / "finally.db"))
    conn = get_connection()
    assert TABLES <= table_names(conn)
    conn.close()


def test_seeds_default_profile(conn):
    seeded = profile.get(conn)
    assert seeded["id"] == "default"
    assert seeded["cash_balance"] == DEFAULT_CASH_BALANCE
    assert seeded["created_at"]


def test_seeds_default_watchlist(conn):
    assert watchlist.list_tickers(conn) == DEFAULT_TICKERS


def test_default_tickers_are_the_ten_from_the_spec(conn):
    assert DEFAULT_TICKERS == [
        "AAPL",
        "GOOGL",
        "MSFT",
        "AMZN",
        "TSLA",
        "NVDA",
        "META",
        "JPM",
        "V",
        "NFLX",
    ]


def test_init_leaves_populated_database_unchanged(db_path, conn):
    with conn:
        profile.set_cash(conn, 1234.5)
        watchlist.remove(conn, "AAPL")
        watchlist.add(conn, "PYPL")
    before = watchlist.list_tickers(conn)

    init_db(db_path)

    assert profile.get(conn)["cash_balance"] == 1234.5
    assert watchlist.list_tickers(conn) == before


def test_init_does_not_resurrect_a_cleared_watchlist(db_path, conn):
    with conn:
        for ticker in watchlist.list_tickers(conn):
            watchlist.remove(conn, ticker)

    init_db(db_path)

    assert watchlist.list_tickers(conn) == []


def test_get_connection_returns_dict_rows(conn):
    row = conn.execute("SELECT id FROM user_profile").fetchone()
    assert dict(row) == {"id": "default"}


def test_trade_side_is_constrained(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO trades (id, ticker, side, quantity, price, executed_at)"
            " VALUES ('x', 'AAPL', 'hold', 1, 1.0, 'now')"
        )


def test_chat_role_is_constrained(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO chat_messages (id, role, content, created_at)"
            " VALUES ('x', 'system', 'hi', 'now')"
        )
