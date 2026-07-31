"""Turning a user-supplied ticker into a price, or a TradeError."""

from __future__ import annotations

from app.market import (
    MarketDataSource,
    PriceCache,
    PricingUnavailableError,
    UnknownSymbolError,
)
from app.market.symbols import InvalidSymbolFormatError, normalize_symbol

from .errors import TradeError


def normalize_ticker(ticker: str) -> str:
    """Uppercase and shape-check a ticker, as a TradeError on failure."""
    try:
        return normalize_symbol(ticker)
    except InvalidSymbolFormatError as exc:
        raise TradeError(f"{ticker!r} is not a valid ticker symbol.") from exc


async def resolve_price(
    cache: PriceCache, source: MarketDataSource, symbol: str
) -> tuple[float, bool]:
    """The cached price for symbol, pricing it on demand if it is unknown.

    Returns the price and whether the symbol had to be newly priced, in which
    case the caller adds it to the watchlist so it keeps streaming.
    """
    price = cache.get_price(symbol)
    if price is not None:
        return price, False

    try:
        price = await source.ensure_priced(symbol)
    except (UnknownSymbolError, InvalidSymbolFormatError) as exc:
        raise TradeError(f"{symbol} is not a symbol this market trades.") from exc
    except PricingUnavailableError as exc:
        raise TradeError(
            f"No price is available for {symbol} right now. Please try again in a moment."
        ) from exc
    return price, True
