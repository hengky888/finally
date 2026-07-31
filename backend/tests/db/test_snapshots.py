"""Tests for the portfolio snapshots accessor."""

from app.db import snapshots


def test_append_returns_the_new_row(conn):
    snapshot = snapshots.append(conn, 10500.25)
    assert snapshot["total_value"] == 10500.25
    assert snapshot["id"]
    assert snapshot["recorded_at"]


def test_append_does_not_expose_user_id(conn):
    snapshot = snapshots.append(conn, 10000.0)
    assert set(snapshot) == {"id", "total_value", "recorded_at"}


def test_list_all_is_oldest_first(conn):
    snapshots.append(conn, 10000.0)
    snapshots.append(conn, 10100.0)
    snapshots.append(conn, 9900.0)

    assert [row["total_value"] for row in snapshots.list_all(conn)] == [
        10000.0,
        10100.0,
        9900.0,
    ]


def test_list_all_is_empty_on_a_fresh_database(conn):
    assert snapshots.list_all(conn) == []
