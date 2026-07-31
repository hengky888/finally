"""Watchlist routes."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import watchlist_service

from .deps import Cache, Conn, Source

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class WatchlistRequest(BaseModel):
    """A ticker to start watching."""

    ticker: str


@router.get("")
async def list_watchlist(conn: Conn, cache: Cache) -> list[dict]:
    """Watched tickers in insertion order, each with its latest price."""
    return watchlist_service.list_with_prices(conn, cache)


@router.post("")
async def add_watchlist(body: WatchlistRequest, conn: Conn, cache: Cache, source: Source) -> dict:
    """Add a ticker and start streaming its price."""
    return await watchlist_service.add_ticker(conn, cache, source, body.ticker)


@router.delete("/{ticker}")
async def remove_watchlist(ticker: str, conn: Conn, cache: Cache, source: Source) -> dict:
    """Stop watching a ticker. A held ticker keeps its price."""
    return await watchlist_service.remove_ticker(conn, cache, source, ticker)
