"""Watchlist reads and mutations, kept in step with the priced ticker set."""

from __future__ import annotations

import sqlite3

from app.db import positions, watchlist
from app.market import MarketDataSource, PriceCache

from .pricing import normalize_ticker, resolve_price


def list_with_prices(conn: sqlite3.Connection, cache: PriceCache) -> list[dict]:
    """Watched tickers in insertion order, each with its latest price."""
    return [_entry(ticker, cache) for ticker in watchlist.list_tickers(conn)]


async def add_ticker(
    conn: sqlite3.Connection,
    cache: PriceCache,
    source: MarketDataSource,
    ticker: str,
) -> dict:
    """Add a ticker to the watchlist and start pricing it.

    Idempotent. Raises TradeError if the market source cannot price the symbol.
    """
    symbol = normalize_ticker(ticker)
    await resolve_price(cache, source, symbol)
    with conn:
        added = watchlist.add(conn, symbol)
    return {**_entry(symbol, cache), "added": added}


async def remove_ticker(
    conn: sqlite3.Connection,
    cache: PriceCache,
    source: MarketDataSource,
    ticker: str,
) -> dict:
    """Remove a ticker from the watchlist.

    A ticker the user still holds stays priced, so the portfolio can always be
    valued. Only an unheld ticker is dropped from the market source.
    """
    symbol = normalize_ticker(ticker)
    with conn:
        removed = watchlist.remove(conn, symbol)
    still_priced = positions.get(conn, symbol) is not None
    if not still_priced:
        await source.remove_ticker(symbol)
    return {"ticker": symbol, "removed": removed, "still_priced": still_priced}


def _entry(ticker: str, cache: PriceCache) -> dict:
    """One watchlist row: the ticker plus its cached price, if any."""
    update = cache.get(ticker)
    if update is None:
        return {
            "ticker": ticker,
            "price": None,
            "previous_price": None,
            "change": 0.0,
            "change_percent": 0.0,
            "direction": "flat",
            "timestamp": None,
        }
    return update.to_dict()
