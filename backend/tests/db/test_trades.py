"""Tests for the trades accessor."""

from app.db import trades


def test_append_returns_the_new_row(conn):
    trade = trades.append(conn, "AAPL", "buy", 10.0, 190.12)
    assert trade["ticker"] == "AAPL"
    assert trade["side"] == "buy"
    assert trade["quantity"] == 10.0
    assert trade["price"] == 190.12
    assert trade["id"]
    assert trade["executed_at"]


def test_append_does_not_expose_user_id(conn):
    trade = trades.append(conn, "AAPL", "buy", 1.0, 190.0)
    assert set(trade) == {"id", "ticker", "side", "quantity", "price", "executed_at"}


def test_append_gives_each_trade_a_unique_id(conn):
    first = trades.append(conn, "AAPL", "buy", 1.0, 190.0)
    second = trades.append(conn, "AAPL", "buy", 1.0, 190.0)
    assert first["id"] != second["id"]


def test_list_recent_is_newest_first(conn):
    trades.append(conn, "AAPL", "buy", 1.0, 190.0)
    trades.append(conn, "TSLA", "buy", 2.0, 250.0)
    trades.append(conn, "AAPL", "sell", 1.0, 191.0)

    assert [row["ticker"] for row in trades.list_recent(conn)] == ["AAPL", "TSLA", "AAPL"]
    assert trades.list_recent(conn)[0]["side"] == "sell"


def test_list_recent_honours_the_limit(conn):
    for _ in range(5):
        trades.append(conn, "AAPL", "buy", 1.0, 190.0)

    assert len(trades.list_recent(conn, limit=2)) == 2


def test_list_recent_defaults_to_fifty(conn):
    for _ in range(55):
        trades.append(conn, "AAPL", "buy", 1.0, 190.0)

    assert len(trades.list_recent(conn)) == 50


def test_list_recent_is_empty_on_a_fresh_database(conn):
    assert trades.list_recent(conn) == []
