"""Tests for the watchlist accessor."""

from app.db import watchlist


def test_add_returns_true_for_new_ticker(conn):
    assert watchlist.add(conn, "PYPL") is True
    assert "PYPL" in watchlist.list_tickers(conn)


def test_add_returns_false_for_duplicate(conn):
    watchlist.add(conn, "PYPL")
    assert watchlist.add(conn, "PYPL") is False
    assert watchlist.list_tickers(conn).count("PYPL") == 1


def test_remove_returns_true_when_present(conn):
    assert watchlist.remove(conn, "AAPL") is True
    assert "AAPL" not in watchlist.list_tickers(conn)


def test_remove_returns_false_when_absent(conn):
    assert watchlist.remove(conn, "ZZZZ") is False


def test_list_keeps_insertion_order(conn):
    watchlist.add(conn, "PYPL")
    watchlist.add(conn, "SHOP")
    assert watchlist.list_tickers(conn)[-2:] == ["PYPL", "SHOP"]


def test_readded_ticker_goes_to_the_end(conn):
    watchlist.remove(conn, "AAPL")
    watchlist.add(conn, "AAPL")
    assert watchlist.list_tickers(conn)[-1] == "AAPL"
