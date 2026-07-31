"""Auto-execution of the actions the assistant asked for.

The returned `actions` record what actually happened, not what was requested:
only executed trades and applied watchlist changes appear in their arrays, and
every rejection appears in `errors`. Chat history must not tell the user their
account did something it did not do.
"""

from __future__ import annotations

import sqlite3

from app.market import MarketDataSource, PriceCache
from app.services import TradeError, portfolio, watchlist_service

from .schema import AssistantResponse, TradeInstruction, WatchlistInstruction


async def execute(
    conn: sqlite3.Connection,
    cache: PriceCache,
    source: MarketDataSource,
    response: AssistantResponse,
) -> dict | None:
    """Run every requested action, then summarize the outcome.

    Returns None when the assistant asked for nothing and nothing failed, so a
    plain conversational turn carries no actions payload.
    """
    trades: list[dict] = []
    changes: list[dict] = []
    errors: list[str] = []

    for instruction in response.trades:
        try:
            trades.append(await _trade(conn, cache, source, instruction))
        except TradeError as exc:
            errors.append(str(exc))

    for instruction in response.watchlist_changes:
        try:
            changes.append(await _watchlist_change(conn, cache, source, instruction))
        except TradeError as exc:
            errors.append(str(exc))

    actions = {"trades": trades, "watchlist_changes": changes, "errors": errors}
    filled = {key: value for key, value in actions.items() if value}
    return filled or None


async def _trade(
    conn: sqlite3.Connection,
    cache: PriceCache,
    source: MarketDataSource,
    instruction: TradeInstruction,
) -> dict:
    """Execute one trade and describe the fill."""
    fill = await portfolio.execute_trade(
        conn, cache, source, instruction.ticker, instruction.side, instruction.quantity
    )
    return {
        "ticker": fill["ticker"],
        "side": fill["side"],
        "quantity": fill["quantity"],
        "price": fill["price"],
    }


async def _watchlist_change(
    conn: sqlite3.Connection,
    cache: PriceCache,
    source: MarketDataSource,
    instruction: WatchlistInstruction,
) -> dict:
    """Apply one watchlist edit."""
    if instruction.action == "add":
        result = await watchlist_service.add_ticker(conn, cache, source, instruction.ticker)
    else:
        result = await watchlist_service.remove_ticker(conn, cache, source, instruction.ticker)
    return {"ticker": result["ticker"], "action": instruction.action}
