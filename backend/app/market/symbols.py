"""Symbol normalization and validation."""

from __future__ import annotations

import re

_SYMBOL_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z]{1,2})?$")


class InvalidSymbolFormatError(ValueError):
    """Raised when a string cannot be a ticker symbol at all."""


def normalize_symbol(raw: str) -> str:
    """Uppercase, strip, and shape-check a user-supplied ticker.

    Raises InvalidSymbolFormatError for anything that is not plausibly a symbol.
    Applies in both simulator and Massive mode.

        >>> normalize_symbol("  aapl ")
        'AAPL'
        >>> normalize_symbol("brk.b")
        'BRK.B'
    """
    symbol = (raw or "").strip().upper()
    if not _SYMBOL_RE.match(symbol):
        raise InvalidSymbolFormatError(f"{raw!r} is not a valid ticker symbol")
    return symbol


# Symbols the simulator will price. The 10 defaults plus liquid large caps a
# user or the LLM is likely to reach for. Anything outside this set is rejected
# in simulator mode rather than given an invented price.
SIMULATED_UNIVERSE: frozenset[str] = frozenset(
    {
        # Defaults
        "AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX",
        # Tech
        "AMD", "INTC", "CRM", "ORCL", "ADBE", "CSCO", "QCOM", "TXN", "AVGO", "IBM",
        "UBER", "ABNB", "SHOP", "SQ", "PYPL", "SNOW", "PLTR", "COIN", "SPOT", "MU",
        # Finance
        "BAC", "WFC", "GS", "MS", "C", "AXP", "MA", "BLK", "SCHW", "BRK.B",
        # Consumer / health / industrial
        "WMT", "COST", "TGT", "HD", "NKE", "SBUX", "MCD", "KO", "PEP", "PG",
        "JNJ", "PFE", "MRK", "LLY", "UNH", "ABBV", "CVS",
        "XOM", "CVX", "BA", "CAT", "GE", "F", "GM", "DIS", "T", "VZ",
        # Index ETFs
        "SPY", "QQQ", "DIA", "IWM", "VTI",
    }
)


def is_simulated(symbol: str) -> bool:
    """True if the simulator has (or can invent) a defensible price for this symbol."""
    return symbol in SIMULATED_UNIVERSE
