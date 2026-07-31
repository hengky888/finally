"""Shared FastAPI dependencies.

The price cache and market data source live on `app.state`, put there when the
app is created and started. A database connection is opened per request and
closed when it finishes.
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request

from app.db import get_connection
from app.market import MarketDataSource, PriceCache


async def get_conn() -> AsyncIterator[sqlite3.Connection]:
    """One SQLite connection for the lifetime of a request.

    Async so the connection is opened on the event loop thread, the same
    thread the async route handlers use. A sqlite3 connection may only be used
    from the thread that created it.
    """
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def get_cache(request: Request) -> PriceCache:
    """The shared in-memory price cache."""
    return request.app.state.price_cache


def get_source(request: Request) -> MarketDataSource:
    """The running market data source."""
    return request.app.state.market_source


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
Cache = Annotated[PriceCache, Depends(get_cache)]
Source = Annotated[MarketDataSource, Depends(get_source)]
