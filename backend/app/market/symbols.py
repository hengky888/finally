"""Symbol normalization and validation."""

from __future__ import annotations

import hashlib
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
# fmt: off  -- grouped by sector and kept tabular; one symbol per line would be
# 60+ lines of noise for no gain.
SIMULATED_UNIVERSE: frozenset[str] = frozenset(
    {
        # Defaults
        "AAPL",
        "GOOGL",
        "MSFT",
        "AMZN",
        "TSLA",
        "NVDA",
        "META",
        "JPM",
        "V",
        "NFLX",
        # Tech
        "AMD",
        "INTC",
        "CRM",
        "ORCL",
        "ADBE",
        "CSCO",
        "QCOM",
        "TXN",
        "AVGO",
        "IBM",
        "UBER",
        "ABNB",
        "SHOP",
        "SQ",
        "PYPL",
        "SNOW",
        "PLTR",
        "COIN",
        "SPOT",
        "MU",
        # Finance
        "BAC",
        "WFC",
        "GS",
        "MS",
        "C",
        "AXP",
        "MA",
        "BLK",
        "SCHW",
        "BRK.B",
        # Consumer / health / industrial
        "WMT",
        "COST",
        "TGT",
        "HD",
        "NKE",
        "SBUX",
        "MCD",
        "KO",
        "PEP",
        "PG",
        "JNJ",
        "PFE",
        "MRK",
        "LLY",
        "UNH",
        "ABBV",
        "CVS",
        "XOM",
        "CVX",
        "BA",
        "CAT",
        "GE",
        "F",
        "GM",
        "DIS",
        "T",
        "VZ",
        # Index ETFs
        "SPY",
        "QQQ",
        "DIA",
        "IWM",
        "VTI",
    }
)
# fmt: on


def is_simulated(symbol: str) -> bool:
    """True if `symbol` is inside the simulated universe.

    A membership test, and the only thing standing between a made-up string and
    a made-up price: symbols outside this set are rejected rather than priced.
    """
    return symbol in SIMULATED_UNIVERSE


def reference_price(symbol: str) -> float:
    """A stable starting price for a universe symbol.

    Seeded symbols use their real-world price. Everything else derives its price
    deterministically from the symbol itself, so a restart reproduces the same
    market instead of inventing a fresh one each boot.
    """
    from .seed_prices import SEED_PRICES

    seeded = SEED_PRICES.get(symbol)
    if seeded is not None:
        return seeded
    # Stable hash → $50-300. hashlib rather than hash() because PYTHONHASHSEED
    # randomizes str hashing per process.
    digest = hashlib.sha256(symbol.encode()).digest()
    return round(50.0 + (int.from_bytes(digest[:4], "big") % 25000) / 100.0, 2)
