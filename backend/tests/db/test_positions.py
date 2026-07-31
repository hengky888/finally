"""Tests for the positions accessor."""

from app.db import positions


def test_get_returns_none_when_absent(conn):
    assert positions.get(conn, "AAPL") is None


def test_upsert_inserts_and_returns_the_row(conn):
    row = positions.upsert(conn, "AAPL", 10.0, 190.0)
    assert row["ticker"] == "AAPL"
    assert row["quantity"] == 10.0
    assert row["avg_cost"] == 190.0
    assert row["updated_at"]


def test_upsert_does_not_expose_user_id(conn):
    row = positions.upsert(conn, "AAPL", 10.0, 190.0)
    assert set(row) == {"ticker", "quantity", "avg_cost", "updated_at"}


def test_upsert_updates_existing_position(conn):
    positions.upsert(conn, "AAPL", 10.0, 190.0)
    positions.upsert(conn, "AAPL", 15.0, 195.0)

    assert positions.get(conn, "AAPL")["quantity"] == 15.0
    assert positions.get(conn, "AAPL")["avg_cost"] == 195.0
    assert len(positions.list_all(conn)) == 1


def test_upsert_supports_fractional_quantities(conn):
    positions.upsert(conn, "AAPL", 0.5, 190.0)
    assert positions.get(conn, "AAPL")["quantity"] == 0.5


def test_list_all_is_ordered_by_ticker(conn):
    positions.upsert(conn, "TSLA", 1.0, 250.0)
    positions.upsert(conn, "AAPL", 2.0, 190.0)
    positions.upsert(conn, "MSFT", 3.0, 420.0)

    assert [row["ticker"] for row in positions.list_all(conn)] == ["AAPL", "MSFT", "TSLA"]


def test_delete_returns_true_when_held(conn):
    positions.upsert(conn, "AAPL", 10.0, 190.0)
    assert positions.delete(conn, "AAPL") is True
    assert positions.get(conn, "AAPL") is None


def test_delete_returns_false_when_absent(conn):
    assert positions.delete(conn, "AAPL") is False


def test_list_all_is_empty_on_a_fresh_database(conn):
    assert positions.list_all(conn) == []
