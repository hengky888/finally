"""Watchlist service behaviour, including the priced-set rule."""

import pytest

from app.db import positions, watchlist
from app.services import TradeError, portfolio, watchlist_service


def test_list_with_prices_uses_the_cache(conn, cache):
    entries = watchlist_service.list_with_prices(conn, cache)
    by_ticker = {entry["ticker"]: entry for entry in entries}

    assert by_ticker["AAPL"]["price"] == 100.0
    assert by_ticker["AAPL"]["direction"] == "flat"


def test_list_with_prices_reports_unpriced_tickers_as_none(conn, cache):
    with conn:
        watchlist.add(conn, "PYPL")

    entry = next(e for e in watchlist_service.list_with_prices(conn, cache) if e["ticker"] == "PYPL")

    assert entry["price"] is None


def test_list_with_prices_keeps_insertion_order(conn, cache):
    tickers = [entry["ticker"] for entry in watchlist_service.list_with_prices(conn, cache)]

    assert tickers == watchlist.list_tickers(conn)


async def test_add_ticker_prices_and_persists_it(conn, cache, source):
    with conn:
        watchlist.remove(conn, "PYPL")

    result = await watchlist_service.add_ticker(conn, cache, source, "pypl")

    assert result["ticker"] == "PYPL"
    assert result["added"] is True
    assert result["price"] == 25.0
    assert "PYPL" in watchlist.list_tickers(conn)


async def test_add_ticker_is_idempotent(conn, cache, source):
    result = await watchlist_service.add_ticker(conn, cache, source, "AAPL")

    assert result["added"] is False
    assert watchlist.list_tickers(conn).count("AAPL") == 1


async def test_add_ticker_rejects_unknown_symbol(conn, cache, source):
    with pytest.raises(TradeError, match="not a symbol this market trades"):
        await watchlist_service.add_ticker(conn, cache, source, "ZZZZ")

    assert "ZZZZ" not in watchlist.list_tickers(conn)


async def test_add_ticker_rejects_malformed_symbol(conn, cache, source):
    with pytest.raises(TradeError, match="not a valid ticker symbol"):
        await watchlist_service.add_ticker(conn, cache, source, "123!")


async def test_remove_unheld_ticker_unprices_it(conn, cache, source):
    result = await watchlist_service.remove_ticker(conn, cache, source, "AAPL")

    assert result == {"ticker": "AAPL", "removed": True, "still_priced": False}
    assert "AAPL" not in watchlist.list_tickers(conn)
    assert cache.get_price("AAPL") is None


async def test_removing_a_held_ticker_keeps_it_priced(conn, cache, source):
    with conn:
        positions.upsert(conn, "AAPL", 5.0, 90.0)

    result = await watchlist_service.remove_ticker(conn, cache, source, "AAPL")

    assert result["removed"] is True
    assert result["still_priced"] is True
    assert cache.get_price("AAPL") == 100.0
    assert "AAPL" in source.get_tickers()
    assert portfolio.get_portfolio(conn, cache)["positions"][0]["current_price"] == 100.0


async def test_remove_absent_ticker_is_a_no_op(conn, cache, source):
    result = await watchlist_service.remove_ticker(conn, cache, source, "PYPL")

    assert result["removed"] is False
