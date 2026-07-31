"""Portfolio valuation and trade execution.

Valuation follows PLAN.md section 8 exactly; the frontend implements the same
formulas and any disagreement is a visible bug.
"""

from __future__ import annotations

import sqlite3

from app.db import positions, profile, snapshots, trades, watchlist
from app.market import MarketDataSource, PriceCache

from .errors import TradeError
from .pricing import normalize_ticker, resolve_price

# A position whose quantity falls inside this band has been fully closed.
QUANTITY_EPSILON = 1e-9

SIDES = ("buy", "sell")


def get_portfolio(conn: sqlite3.Connection, cache: PriceCache) -> dict:
    """Cash, valued positions, total value and total unrealized P&L."""
    cash_balance = profile.get(conn)["cash_balance"]
    valued = [_value_position(row, cache) for row in positions.list_all(conn)]
    return {
        "cash_balance": cash_balance,
        "positions": valued,
        "total_value": cash_balance + sum(p["position_value"] for p in valued),
        "total_unrealized_pnl": sum(p["unrealized_pnl"] for p in valued),
    }


def record_snapshot(conn: sqlite3.Connection, cache: PriceCache) -> dict:
    """Write the current total portfolio value to portfolio_snapshots."""
    with conn:
        return snapshots.append(conn, get_portfolio(conn, cache)["total_value"])


def list_history(conn: sqlite3.Connection) -> list[dict]:
    """Every portfolio value snapshot, oldest first."""
    return snapshots.list_all(conn)


def priced_tickers(conn: sqlite3.Connection) -> list[str]:
    """The set that must stay priced: watchlist union open positions.

    A ticker the user still holds keeps its price after leaving the watchlist,
    so the portfolio can always be valued.
    """
    tickers = list(watchlist.list_tickers(conn))
    held = {row["ticker"] for row in positions.list_all(conn)}
    tickers.extend(sorted(held - set(tickers)))
    return tickers


async def execute_trade(
    conn: sqlite3.Connection,
    cache: PriceCache,
    source: MarketDataSource,
    ticker: str,
    side: str,
    quantity: float,
) -> dict:
    """Fill a whole order at the cached price, or raise TradeError.

    The fill price comes from the price cache, never from the caller. The
    trade row, the position, the cash balance and the snapshot are written as
    one transaction, so a failure cannot debit cash without delivering shares.
    """
    symbol = normalize_ticker(ticker)
    side = _validate_side(side)
    quantity = _validate_quantity(quantity)

    price, newly_priced = await resolve_price(cache, source, symbol)

    cash_balance = profile.get(conn)["cash_balance"]
    position = positions.get(conn, symbol)
    new_quantity, new_avg_cost, new_cash = _settle(
        symbol, side, quantity, price, cash_balance, position
    )

    with conn:
        if newly_priced:
            watchlist.add(conn, symbol)
        trade = trades.append(conn, symbol, side, quantity, price)
        if new_quantity <= QUANTITY_EPSILON:
            positions.delete(conn, symbol)
            new_position = None
        else:
            new_position = positions.upsert(conn, symbol, new_quantity, new_avg_cost)
        profile.set_cash(conn, new_cash)
        total_value = get_portfolio(conn, cache)["total_value"]
        snapshots.append(conn, total_value)

    return {
        **trade,
        "cash_balance": new_cash,
        "position": new_position,
        "total_value": total_value,
    }


def _settle(
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    cash_balance: float,
    position: dict | None,
) -> tuple[float, float, float]:
    """Validate the whole order and return the resulting quantity, cost and cash.

    A buy averages the new lot into the cost basis; a sell leaves it untouched.
    """
    held = position["quantity"] if position else 0.0
    avg_cost = position["avg_cost"] if position else 0.0

    if side == "buy":
        cost = quantity * price
        if cost > cash_balance + QUANTITY_EPSILON:
            raise TradeError(
                f"Insufficient cash: buying {quantity:g} {symbol} at ${price:,.2f} "
                f"costs ${cost:,.2f}, but only ${cash_balance:,.2f} is available."
            )
        new_quantity = held + quantity
        return new_quantity, (held * avg_cost + cost) / new_quantity, cash_balance - cost

    if quantity > held + QUANTITY_EPSILON:
        raise TradeError(f"Cannot sell {quantity:g} {symbol}: only {held:g} shares are held.")
    return held - quantity, avg_cost, cash_balance + quantity * price


def _value_position(row: dict, cache: PriceCache) -> dict:
    """Apply the PLAN.md section 8 valuation formulas to one position."""
    quantity = row["quantity"]
    avg_cost = row["avg_cost"]
    # Positions are always in the priced set; avg_cost is the honest fallback
    # in the moment before the source has published a first tick.
    cached = cache.get_price(row["ticker"])
    current_price = avg_cost if cached is None else cached
    return {
        "ticker": row["ticker"],
        "quantity": quantity,
        "avg_cost": avg_cost,
        "current_price": current_price,
        "position_value": quantity * current_price,
        "unrealized_pnl": quantity * (current_price - avg_cost),
        "pnl_pct": (current_price - avg_cost) / avg_cost if avg_cost else 0.0,
    }


def _validate_side(side: str) -> str:
    normalized = (side or "").strip().lower()
    if normalized not in SIDES:
        raise TradeError(f"Side must be 'buy' or 'sell', not {side!r}.")
    return normalized


def _validate_quantity(quantity: float) -> float:
    if quantity <= 0:
        raise TradeError("Quantity must be greater than zero.")
    return float(quantity)
