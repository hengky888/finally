"""Tests for the profile accessor."""

from app.db import get_connection, profile


def test_get_returns_expected_keys(conn):
    assert set(profile.get(conn)) == {"id", "cash_balance", "created_at"}


def test_set_cash_persists_across_connections(conn):
    with conn:
        profile.set_cash(conn, 250.75)

    other = get_connection()
    assert profile.get(other)["cash_balance"] == 250.75
    other.close()


def test_set_cash_accepts_zero(conn):
    profile.set_cash(conn, 0.0)
    assert profile.get(conn)["cash_balance"] == 0.0
