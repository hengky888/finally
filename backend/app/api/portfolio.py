"""Portfolio routes: valuation, trade execution and value history."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import portfolio

from .deps import Cache, Conn, Source

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


class TradeRequest(BaseModel):
    """A trade order. The fill price is set by the server, never the client."""

    ticker: str
    quantity: float
    side: str


@router.get("")
async def get_portfolio(conn: Conn, cache: Cache) -> dict:
    """Cash, positions valued at the latest prices, total value and P&L."""
    return portfolio.get_portfolio(conn, cache)


@router.post("/trade")
async def execute_trade(order: TradeRequest, conn: Conn, cache: Cache, source: Source) -> dict:
    """Execute a whole order at the current cached price."""
    return await portfolio.execute_trade(
        conn, cache, source, order.ticker, order.side, order.quantity
    )


@router.get("/history")
async def get_history(conn: Conn) -> list[dict]:
    """Portfolio value snapshots, oldest first, for the P&L chart."""
    return portfolio.list_history(conn)
