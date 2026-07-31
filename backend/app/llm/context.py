"""The portfolio snapshot handed to the model as prompt context."""

from __future__ import annotations

import sqlite3

from app.market import PriceCache
from app.services import portfolio, watchlist_service


def build(conn: sqlite3.Connection, cache: PriceCache) -> str:
    """Render cash, positions with P&L and the priced watchlist as plain text."""
    holdings = portfolio.get_portfolio(conn, cache)
    lines = [
        "Current portfolio:",
        f"  Cash: ${holdings['cash_balance']:,.2f}",
        f"  Total value: ${holdings['total_value']:,.2f}",
        f"  Total unrealized P&L: ${holdings['total_unrealized_pnl']:,.2f}",
        "  Positions:",
    ]
    lines.extend(_position_lines(holdings["positions"]))
    lines.append("Watchlist:")
    lines.extend(_watchlist_lines(watchlist_service.list_with_prices(conn, cache)))
    return "\n".join(lines)


def _position_lines(positions: list[dict]) -> list[str]:
    if not positions:
        return ["    (none)"]
    return [
        f"    {p['ticker']}: {p['quantity']:g} shares @ ${p['avg_cost']:,.2f} avg cost, "
        f"now ${p['current_price']:,.2f}, value ${p['position_value']:,.2f}, "
        f"P&L ${p['unrealized_pnl']:,.2f} ({p['pnl_pct'] * 100:+.2f}%)"
        for p in positions
    ]


def _watchlist_lines(entries: list[dict]) -> list[str]:
    if not entries:
        return ["  (empty)"]
    return [
        f"  {e['ticker']}: "
        + (f"${e['price']:,.2f} ({e['change_percent']:+.2f}%)" if e["price"] else "no price yet")
        for e in entries
    ]
