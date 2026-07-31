"""Tests for caller-owned transactions."""

import pytest

from app.db import get_connection, positions, profile, snapshots, trades


def test_implicit_transactions_are_enabled(conn):
    assert conn.isolation_level == ""


def test_rollback_discards_the_whole_unit_of_work(conn):
    with pytest.raises(RuntimeError):
        with conn:
            trades.append(conn, "AAPL", "buy", 10.0, 190.0)
            positions.upsert(conn, "AAPL", 10.0, 190.0)
            profile.set_cash(conn, 8100.0)
            raise RuntimeError("fill rejected mid-write")

    assert positions.get(conn, "AAPL") is None
    assert trades.list_recent(conn) == []
    assert profile.get(conn)["cash_balance"] == 10000.0


def test_commit_persists_the_whole_unit_of_work(conn):
    with conn:
        trades.append(conn, "AAPL", "buy", 10.0, 190.0)
        positions.upsert(conn, "AAPL", 10.0, 190.0)
        profile.set_cash(conn, 8100.0)
        snapshots.append(conn, 10000.0)

    other = get_connection()
    assert other is not conn
    assert positions.get(other, "AAPL")["quantity"] == 10.0
    assert len(other.execute("SELECT id FROM trades").fetchall()) == 1
    assert profile.get(other)["cash_balance"] == 8100.0
    assert len(snapshots.list_all(other)) == 1
    other.close()


def test_accessors_do_not_commit_on_their_own(conn):
    positions.upsert(conn, "AAPL", 10.0, 190.0)
    conn.rollback()

    assert positions.get(conn, "AAPL") is None
