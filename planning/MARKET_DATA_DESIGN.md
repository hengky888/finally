# Market Data Backend — Detailed Design

Implementation-ready design for the FinAlly market data subsystem: the unified `MarketDataSource` interface, the shared `PriceCache`, the GBM simulator, the Massive (Polygon.io) REST client, symbol validation, and the SSE streaming endpoint.

Everything described here lives under `backend/app/market/`.

**Status of the code.** Most of this subsystem is already built and tested (73 tests, 84% coverage — see `MARKET_DATA_SUMMARY.md`). This document is the *current* design of record: it describes the as-built code and specifies four changes needed to close contract gaps found in review (`REVIEW.md` findings on SSE cadence, unpriced-ticker fills, and symbol validation). Each snippet is labelled **as built** or **change required** so an implementing agent knows what to write.

---

## Table of Contents

1. [Architecture](#1-architecture)
2. [File Structure](#2-file-structure)
3. [Data Model — `models.py`](#3-data-model--modelspy)
4. [Price Cache — `cache.py`](#4-price-cache--cachepy)
5. [Symbol Validation — `symbols.py`](#5-symbol-validation--symbolspy)
6. [Unified Interface — `interface.py`](#6-unified-interface--interfacepy)
7. [Seed Prices & Parameters — `seed_prices.py`](#7-seed-prices--parameters--seed_pricespy)
8. [GBM Simulator — `simulator.py`](#8-gbm-simulator--simulatorpy)
9. [Massive API Client — `massive_client.py`](#9-massive-api-client--massive_clientpy)
10. [Factory — `factory.py`](#10-factory--factorypy)
11. [SSE Streaming — `stream.py`](#11-sse-streaming--streampy)
12. [FastAPI Lifecycle Integration](#12-fastapi-lifecycle-integration)
13. [Watchlist & Trade Coordination](#13-watchlist--trade-coordination)
14. [Error Handling & Edge Cases](#14-error-handling--edge-cases)
15. [Testing Strategy](#15-testing-strategy)
16. [Configuration Summary](#16-configuration-summary)
17. [Delta From the Shipped Code](#17-delta-from-the-shipped-code)

---

## 1. Architecture

One abstract interface, two implementations, one shared cache. Every consumer downstream of the cache is source-agnostic — nothing outside `app/market/` knows or cares whether prices come from GBM or from Polygon.

```
                  MASSIVE_API_KEY?
                        │
        ┌───────────────┴───────────────┐
        │ no                            │ yes
        ▼                               ▼
 SimulatorDataSource            MassiveDataSource
 (GBM, 500 ms ticks)            (REST poll, 2-15 s)
        │                               │
        └───────────────┬───────────────┘
                        ▼
                   PriceCache            ← single point of truth
                  (thread-safe)             (latest price per ticker)
                        │
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
   SSE endpoint    Portfolio        Trade execution
 /api/stream/prices  valuation      (fill price lookup)
```

**Invariants the rest of the backend can rely on:**

1. The cache is written *only* by the active data source; everyone else reads.
2. The priced set is `watchlist ∪ open positions` (PLAN §6). Held tickers stay priced after leaving the watchlist so the portfolio can always be valued.
3. A ticker present in the cache always has a usable, non-negative fill price.
4. Data sources never raise into their background loops — a failed tick or poll is logged and retried.

---

## 2. File Structure

```
backend/app/market/
├── __init__.py           # Public re-exports
├── models.py             # PriceUpdate dataclass
├── cache.py              # PriceCache (thread-safe store)
├── interface.py          # MarketDataSource ABC + exceptions
├── symbols.py            # NEW — symbol normalization + universe validation
├── seed_prices.py        # SEED_PRICES, TICKER_PARAMS, correlation config
├── simulator.py          # GBMSimulator + SimulatorDataSource
├── massive_client.py     # MassiveDataSource
├── factory.py            # create_market_data_source()
└── stream.py             # SSE endpoint (FastAPI router factory)
```

`__init__.py` re-exports the public API so the rest of the backend never reaches into submodules:

```python
"""Market data subsystem for FinAlly."""

from .cache import PriceCache
from .factory import create_market_data_source
from .interface import MarketDataSource, PricingUnavailableError, UnknownSymbolError
from .models import PriceUpdate
from .stream import create_stream_router
from .symbols import normalize_symbol

__all__ = [
    "PriceUpdate",
    "PriceCache",
    "MarketDataSource",
    "UnknownSymbolError",
    "PricingUnavailableError",
    "create_market_data_source",
    "create_stream_router",
    "normalize_symbol",
]
```

---

## 3. Data Model — `models.py`

**As built.** `PriceUpdate` is the only type that leaves the market layer.

```python
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Immutable snapshot of a single ticker's price at a point in time."""

    ticker: str
    price: float
    previous_price: float
    timestamp: float = field(default_factory=time.time)  # Unix seconds

    @property
    def change(self) -> float:
        """Absolute price change from previous update."""
        return round(self.price - self.previous_price, 4)

    @property
    def change_percent(self) -> float:
        if self.previous_price == 0:
            return 0.0
        return round((self.price - self.previous_price) / self.previous_price * 100, 4)

    @property
    def direction(self) -> str:
        """'up', 'down', or 'flat'."""
        if self.price > self.previous_price:
            return "up"
        elif self.price < self.previous_price:
            return "down"
        return "flat"

    def to_dict(self) -> dict:
        """Serialize for JSON / SSE transmission."""
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "timestamp": self.timestamp,
            "change": self.change,
            "change_percent": self.change_percent,
            "direction": self.direction,
        }
```

### Why it's shaped this way

- **`frozen=True`** — a `PriceUpdate` is a value object. Once created it never mutates, so it is safe to hand to any number of async readers without copying.
- **`slots=True`** — we create ~20 of these per second for the lifetime of the container; slots keeps the footprint flat.
- **Derived properties, not stored fields** — `change`, `change_percent`, and `direction` are computed from `price` and `previous_price`, so they can never drift out of sync with each other.
- **`previous_price` is "previous write to the cache"**, not "previous close". Day-over-day change is a separate concern; if the frontend needs it later, add a `previous_close` field populated from the Massive `day.previous_close` and defaulted to the session seed in simulator mode.

> **Note on `direction`.** `PriceUpdate.direction` is relative to the previous *cache write*. That is not the same as "changed since the last SSE event the client saw" — in Massive mode, the cached update sits unchanged between polls, still reporting `"up"` from the last poll. §11 explains why the SSE layer computes its own per-connection direction rather than forwarding this one.

---

## 4. Price Cache — `cache.py`

**As built.** A `threading.Lock` guards a plain dict. The lock (rather than a bare dict or an asyncio primitive) is required because the Massive client writes from a worker thread via `asyncio.to_thread`, while SSE readers run on the event loop.

```python
from __future__ import annotations

import time
from threading import Lock

from .models import PriceUpdate


class PriceCache:
    """Thread-safe in-memory cache of the latest price for each ticker.

    Writers: SimulatorDataSource or MassiveDataSource (one at a time).
    Readers: SSE streaming endpoint, portfolio valuation, trade execution.
    """

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self._lock = Lock()
        self._version: int = 0  # Monotonic; bumped on every update

    def update(self, ticker: str, price: float, timestamp: float | None = None) -> PriceUpdate:
        """Record a new price. Returns the created PriceUpdate.

        On the first update for a ticker, previous_price == price (direction 'flat').
        """
        with self._lock:
            ts = timestamp or time.time()
            prev = self._prices.get(ticker)
            previous_price = prev.price if prev else price

            update = PriceUpdate(
                ticker=ticker,
                price=round(price, 2),
                previous_price=round(previous_price, 2),
                timestamp=ts,
            )
            self._prices[ticker] = update
            self._version += 1
            return update

    def get(self, ticker: str) -> PriceUpdate | None:
        with self._lock:
            return self._prices.get(ticker)

    def get_all(self) -> dict[str, PriceUpdate]:
        """Snapshot of all current prices. Returns a shallow copy."""
        with self._lock:
            return dict(self._prices)

    def get_price(self, ticker: str) -> float | None:
        update = self.get(ticker)
        return update.price if update else None

    def remove(self, ticker: str) -> None:
        with self._lock:
            self._prices.pop(ticker, None)

    @property
    def version(self) -> int:
        with self._lock:                # change required: was an unlocked read
            return self._version

    def __len__(self) -> int:
        with self._lock:
            return len(self._prices)

    def __contains__(self, ticker: str) -> bool:
        with self._lock:
            return ticker in self._prices
```

**Change required (minor):** take the lock in `version`. The unlocked read is safe under CPython's GIL today but is inconsistent with the rest of the class and becomes a real race on free-threaded builds. The cost is one uncontended lock acquisition twice a second.

**Rounding contract.** The cache rounds to 2 decimals on write, so every consumer sees the same cent-precision price. Rounding at the boundary (rather than in each data source) means the fill price a trade executes at is byte-identical to the price the user saw stream past.

**Memory.** O(number of priced tickers) — one `PriceUpdate` each, replaced on write. There is no history in the cache; the price series shown in the UI is accumulated client-side from SSE (PLAN §10), and portfolio history lives in `portfolio_snapshots`.

---

## 5. Symbol Validation — `symbols.py`

**New module. Closes `REVIEW.md` finding "Add source-independent ticker validation".**

The problem: PLAN §8 says an unrecognized symbol is rejected, but the simulator will happily assign `NOT_A_STOCK` a random price between $50 and $300 and let the user trade it. Validation has to happen *before* either the data source or the watchlist table is mutated, and it has to behave the same way in both modes for the symbols users actually type.

Two layers:

1. **Shape validation** (both modes) — 1-5 uppercase letters, optionally `.` plus one or two letters for share classes (`BRK.B`). Cheap, catches typos and injection-ish input.
2. **Existence validation** (mode-specific) — the simulator checks a curated universe; Massive asks the API. Both reject `NOT_A_STOCK`; the simulator is stricter about genuinely obscure real symbols, which is the right trade-off for a demo that must never show a plausible-looking price for a symbol that doesn't exist.

```python
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
        >>> normalize_symbol("NOT_A_STOCK")
        Traceback (most recent call last):
        InvalidSymbolFormatError: 'NOT_A_STOCK' is not a valid ticker symbol
    """
    symbol = (raw or "").strip().upper()
    if not _SYMBOL_RE.match(symbol):
        raise InvalidSymbolFormatError(f"{raw!r} is not a valid ticker symbol")
    return symbol


# Symbols the simulator will price. The 10 defaults plus liquid large caps a
# user or the LLM is likely to reach for. Anything outside this set is rejected
# in simulator mode rather than given an invented price.
SIMULATED_UNIVERSE: frozenset[str] = frozenset({
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
})


def is_simulated(symbol: str) -> bool:
    """True if the simulator has (or can invent) a defensible price for this symbol."""
    return symbol in SIMULATED_UNIVERSE
```

Extending the universe is a one-line edit; symbols in it but absent from `SEED_PRICES` get a random seed price and `DEFAULT_PARAMS`, which is fine — they are real companies, just not ones we hand-tuned.

---

## 6. Unified Interface — `interface.py`

The ABC every data source implements. Five methods are **as built**; `ensure_priced` is **change required** and is the heart of §13.

```python
"""Abstract interface for market data sources."""

from __future__ import annotations

from abc import ABC, abstractmethod


class UnknownSymbolError(Exception):
    """The symbol is not tradeable by this source. Permanent — do not retry.

    Maps to HTTP 400.
    """


class PricingUnavailableError(Exception):
    """The symbol may be valid but no price could be obtained right now.

    Transient (API timeout, rate limit, network). Maps to HTTP 503.
    """


class MarketDataSource(ABC):
    """Contract for market data providers.

    Implementations push price updates into a shared PriceCache on their own
    schedule. Downstream code never calls the data source for prices — it
    reads the cache.

    Lifecycle:
        source = create_market_data_source(cache)
        await source.start(["AAPL", "GOOGL", ...])
        await source.add_ticker("TSLA")
        price = await source.ensure_priced("PYPL")   # blocking, for trades
        await source.remove_ticker("GOOGL")
        await source.stop()
    """

    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Begin producing price updates for the given tickers.

        Starts a background task that periodically writes to the PriceCache.
        Must be called exactly once; calling start() twice is undefined.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Stop the background task and release resources. Idempotent."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Add a ticker to the active set. No-op if already present.

        Fire-and-forget: does NOT guarantee a price exists on return.
        Use ensure_priced() when a price is required immediately.
        """

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker from the active set and from the cache. No-op if absent."""

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Return the current list of actively tracked tickers."""

    @abstractmethod
    async def ensure_priced(self, ticker: str, timeout: float = 5.0) -> float:
        """Guarantee the cache holds a price for `ticker`, and return it.

        Adds the ticker to the active set as a side effect *only on success*.
        Blocks until a price is available or `timeout` elapses.

        Raises:
            UnknownSymbolError: the source cannot price this symbol (permanent).
            PricingUnavailableError: no price obtainable right now (transient).
        """
```

### Why `ensure_priced` exists

`add_ticker` is deliberately fire-and-forget: the watchlist UI doesn't need to block, and in Massive mode a new ticker simply appears on the next poll. But PLAN §8 requires a trade in an unpriced ticker to auto-add it and fill *at execution time*. In Massive mode `add_ticker` can leave the caller waiting up to 15 seconds for a price that may never come (bad symbol). `ensure_priced` is the synchronous, fallible counterpart: it either returns a price you can fill against or raises a typed error the route maps to a status code. This closes the `REVIEW.md` finding "Define how an unpriced Massive ticker gets a fill price".

---

## 7. Seed Prices & Parameters — `seed_prices.py`

**As built.** Pure constants, no logic.

```python
"""Seed prices and per-ticker parameters for the market simulator."""

SEED_PRICES: dict[str, float] = {
    "AAPL": 190.00, "GOOGL": 175.00, "MSFT": 420.00, "AMZN": 185.00,
    "TSLA": 250.00, "NVDA": 800.00, "META": 500.00, "JPM": 195.00,
    "V": 280.00, "NFLX": 600.00,
}

# sigma: annualized volatility (higher = more movement); mu: annualized drift
TICKER_PARAMS: dict[str, dict[str, float]] = {
    "AAPL":  {"sigma": 0.22, "mu": 0.05},
    "GOOGL": {"sigma": 0.25, "mu": 0.05},
    "MSFT":  {"sigma": 0.20, "mu": 0.05},
    "AMZN":  {"sigma": 0.28, "mu": 0.05},
    "TSLA":  {"sigma": 0.50, "mu": 0.03},  # High volatility
    "NVDA":  {"sigma": 0.40, "mu": 0.08},  # High volatility, strong drift
    "META":  {"sigma": 0.30, "mu": 0.05},
    "JPM":   {"sigma": 0.18, "mu": 0.04},  # Low volatility (bank)
    "V":     {"sigma": 0.17, "mu": 0.04},  # Low volatility (payments)
    "NFLX":  {"sigma": 0.35, "mu": 0.05},
}

DEFAULT_PARAMS: dict[str, float] = {"sigma": 0.25, "mu": 0.05}

CORRELATION_GROUPS: dict[str, set[str]] = {
    "tech": {"AAPL", "GOOGL", "MSFT", "AMZN", "META", "NVDA", "NFLX"},
    "finance": {"JPM", "V"},
}

INTRA_TECH_CORR = 0.6     # Tech stocks move together
INTRA_FINANCE_CORR = 0.5  # Finance stocks move together
CROSS_GROUP_CORR = 0.3    # Between sectors / unknown tickers
TSLA_CORR = 0.3           # TSLA does its own thing
```

The volatility spread is what makes the terminal look alive: TSLA at `sigma=0.50` visibly jitters while V at `0.17` barely moves, which is exactly the real-world contrast a user expects to see.

---

## 8. GBM Simulator — `simulator.py`

### 8.1 The math

Each tick advances every price by one step of Geometric Brownian Motion:

```
S(t+dt) = S(t) · exp( (mu − sigma²/2)·dt  +  sigma·√dt·Z )
```

- `mu` — annualized drift, `sigma` — annualized volatility, `Z` — correlated standard normal.
- `dt` is 500 ms as a fraction of a *trading* year: `252 days × 6.5 h × 3600 s = 5,896,800 s`, so `dt = 0.5 / 5,896,800 ≈ 8.48e-8`.
- The `−sigma²/2` term is the Itô correction; without it the simulated mean return exceeds `mu`.
- Because the update is multiplicative through `exp()`, prices are always positive — no clamping needed.

Sub-cent per-tick moves accumulate into realistic-looking intraday paths over a few minutes of watching.

### 8.2 Correlated moves

Independent random walks look wrong — real tech names move together. We draw `n` independent normals and multiply by the Cholesky factor `L` of the correlation matrix `C` (`C = L·Lᵀ`), giving draws with exactly the target correlation structure:

```
Z_correlated = L @ Z_independent
```

The matrix is rebuilt on every add/remove. That's O(n²) construction plus O(n³) decomposition, but n < 50 and changes are rare (a watchlist edit), so it is irrelevant next to the 500 ms tick budget.

### 8.3 `GBMSimulator`

**As built.**

```python
from __future__ import annotations

import asyncio
import logging
import math
import random

import numpy as np

from .cache import PriceCache
from .interface import MarketDataSource, PricingUnavailableError, UnknownSymbolError
from .seed_prices import (
    CORRELATION_GROUPS, CROSS_GROUP_CORR, DEFAULT_PARAMS,
    INTRA_FINANCE_CORR, INTRA_TECH_CORR, SEED_PRICES, TICKER_PARAMS, TSLA_CORR,
)
from .symbols import is_simulated, normalize_symbol

logger = logging.getLogger(__name__)


class GBMSimulator:
    """Geometric Brownian Motion simulator for correlated stock prices."""

    # 252 trading days * 6.5 hours/day * 3600 s/hour = 5,896,800 s
    TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600
    DEFAULT_DT = 0.5 / TRADING_SECONDS_PER_YEAR  # ~8.48e-8

    def __init__(
        self,
        tickers: list[str],
        dt: float = DEFAULT_DT,
        event_probability: float = 0.001,
    ) -> None:
        self._dt = dt
        self._event_prob = event_probability
        self._tickers: list[str] = []
        self._prices: dict[str, float] = {}
        self._params: dict[str, dict[str, float]] = {}
        self._cholesky: np.ndarray | None = None

        for ticker in tickers:
            self._add_ticker_internal(ticker)
        self._rebuild_cholesky()

    def step(self) -> dict[str, float]:
        """Advance all tickers one time step. Returns {ticker: new_price}.

        Hot path — called every 500 ms. Keep it fast.
        """
        n = len(self._tickers)
        if n == 0:
            return {}

        z_independent = np.random.standard_normal(n)
        if self._cholesky is not None:
            z_correlated = self._cholesky @ z_independent
        else:
            z_correlated = z_independent

        result: dict[str, float] = {}
        for i, ticker in enumerate(self._tickers):
            params = self._params[ticker]
            mu, sigma = params["mu"], params["sigma"]

            drift = (mu - 0.5 * sigma**2) * self._dt
            diffusion = sigma * math.sqrt(self._dt) * z_correlated[i]
            self._prices[ticker] *= math.exp(drift + diffusion)

            # Random event: ~0.1% per ticker per tick. With 10 tickers at
            # 2 ticks/sec, expect a visible shock roughly every 50 seconds.
            if random.random() < self._event_prob:
                shock_magnitude = random.uniform(0.02, 0.05)
                shock_sign = random.choice([-1, 1])
                self._prices[ticker] *= 1 + shock_magnitude * shock_sign
                logger.debug(
                    "Random event on %s: %.1f%% %s", ticker,
                    shock_magnitude * 100, "up" if shock_sign > 0 else "down",
                )

            result[ticker] = round(self._prices[ticker], 2)

        return result

    def add_ticker(self, ticker: str) -> None:
        if ticker in self._prices:
            return
        self._add_ticker_internal(ticker)
        self._rebuild_cholesky()

    def remove_ticker(self, ticker: str) -> None:
        if ticker not in self._prices:
            return
        self._tickers.remove(ticker)
        del self._prices[ticker]
        del self._params[ticker]
        self._rebuild_cholesky()

    def get_price(self, ticker: str) -> float | None:
        return self._prices.get(ticker)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    # --- Internals ---

    def _add_ticker_internal(self, ticker: str) -> None:
        """Add without rebuilding Cholesky (for batch initialization)."""
        if ticker in self._prices:
            return
        self._tickers.append(ticker)
        self._prices[ticker] = SEED_PRICES.get(ticker, random.uniform(50.0, 300.0))
        self._params[ticker] = TICKER_PARAMS.get(ticker, dict(DEFAULT_PARAMS))

    def _rebuild_cholesky(self) -> None:
        """Rebuild the Cholesky factor of the correlation matrix. O(n^2), n < 50."""
        n = len(self._tickers)
        if n <= 1:
            self._cholesky = None
            return

        corr = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                rho = self._pairwise_correlation(self._tickers[i], self._tickers[j])
                corr[i, j] = rho
                corr[j, i] = rho

        self._cholesky = np.linalg.cholesky(corr)

    @staticmethod
    def _pairwise_correlation(t1: str, t2: str) -> float:
        """Sector-based correlation: tech 0.6, finance 0.5, TSLA 0.3, cross 0.3."""
        tech = CORRELATION_GROUPS["tech"]
        finance = CORRELATION_GROUPS["finance"]

        # TSLA sits in the tech set but behaves independently
        if t1 == "TSLA" or t2 == "TSLA":
            return TSLA_CORR
        if t1 in tech and t2 in tech:
            return INTRA_TECH_CORR
        if t1 in finance and t2 in finance:
            return INTRA_FINANCE_CORR
        return CROSS_GROUP_CORR
```

> **Positive semi-definiteness.** `np.linalg.cholesky` raises `LinAlgError` on a non-PSD matrix. The current three-tier structure (0.6 / 0.5 / 0.3) is PSD for any ticker mix, but anyone widening the spread — say tech to 0.9 while cross stays 0.1 — can break it. §14.6 specifies the guard.

### 8.4 `SimulatorDataSource`

**As built, plus `ensure_priced`.**

```python
class SimulatorDataSource(MarketDataSource):
    """MarketDataSource backed by the GBM simulator.

    Runs a background asyncio task that calls GBMSimulator.step() every
    `update_interval` seconds and writes results to the PriceCache.
    """

    def __init__(
        self,
        price_cache: PriceCache,
        update_interval: float = 0.5,
        event_probability: float = 0.001,
    ) -> None:
        self._cache = price_cache
        self._interval = update_interval
        self._event_prob = event_probability
        self._sim: GBMSimulator | None = None
        self._task: asyncio.Task | None = None

    async def start(self, tickers: list[str]) -> None:
        self._sim = GBMSimulator(tickers=tickers, event_probability=self._event_prob)
        # Seed the cache immediately so the first SSE event carries real data
        for ticker in tickers:
            price = self._sim.get_price(ticker)
            if price is not None:
                self._cache.update(ticker=ticker, price=price)
        self._task = asyncio.create_task(self._run_loop(), name="simulator-loop")
        logger.info("Simulator started with %d tickers", len(tickers))

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("Simulator stopped")

    async def add_ticker(self, ticker: str) -> None:
        if self._sim:
            self._sim.add_ticker(ticker)
            price = self._sim.get_price(ticker)
            if price is not None:
                self._cache.update(ticker=ticker, price=price)
            logger.info("Simulator: added ticker %s", ticker)

    async def remove_ticker(self, ticker: str) -> None:
        if self._sim:
            self._sim.remove_ticker(ticker)
        self._cache.remove(ticker)
        logger.info("Simulator: removed ticker %s", ticker)

    def get_tickers(self) -> list[str]:
        return self._sim.get_tickers() if self._sim else []

    # change required — new method
    async def ensure_priced(self, ticker: str, timeout: float = 5.0) -> float:
        """Validate against the simulated universe, then seed a price synchronously.

        The simulator is authoritative and instantaneous: if the symbol is in the
        universe we can always produce a price, so `timeout` is unused here.
        """
        symbol = normalize_symbol(ticker)          # raises InvalidSymbolFormatError
        if not is_simulated(symbol):
            raise UnknownSymbolError(
                f"{symbol} is not a symbol this simulated market trades"
            )
        cached = self._cache.get_price(symbol)
        if cached is not None:
            return cached
        await self.add_ticker(symbol)              # seeds the cache synchronously
        price = self._cache.get_price(symbol)
        if price is None:                          # only if start() was never called
            raise PricingUnavailableError(f"Market data not running; cannot price {symbol}")
        return price

    async def _run_loop(self) -> None:
        """Core loop: step the simulation, write to cache, sleep."""
        while True:
            try:
                if self._sim:
                    prices = self._sim.step()
                    for ticker, price in prices.items():
                        self._cache.update(ticker=ticker, price=price)
            except Exception:
                logger.exception("Simulator step failed")
            await asyncio.sleep(self._interval)
```

The bare `except Exception` in `_run_loop` is deliberate: a background task that dies takes the whole market with it and the user sees prices silently freeze. Log and keep ticking.

---

## 9. Massive API Client — `massive_client.py`

### 9.1 The API

- Package `massive` (`uv add massive`), successor to `polygon`. Base URL `https://api.massive.com`.
- Auth: `RESTClient(api_key=...)` sends `Authorization: Bearer <key>`.
- Rate limits: free tier 5 req/min → poll every 15 s. Paid tiers → 2-5 s.
- **One endpoint does the work.** `get_snapshot_all(market_type=STOCKS, tickers=[...])` returns every requested ticker in a *single* call, which is what keeps a 10-ticker watchlist inside the free tier's 5 req/min.

Relevant response fields per snapshot:

```json
{
  "ticker": "AAPL",
  "day":        { "previous_close": 129.61, "change_percent": -3.50, "volume": 111237700 },
  "last_trade": { "price": 125.07, "size": 100, "timestamp": 1675190399000 }
}
```

We read `last_trade.price` and `last_trade.timestamp` (Unix **milliseconds** → divide by 1000).

### 9.2 Implementation

**As built, plus `ensure_priced` and symbol normalization.**

```python
"""Massive (Polygon.io) API client for real market data."""

from __future__ import annotations

import asyncio
import logging

from massive import RESTClient
from massive.rest.models import SnapshotMarketType

from .cache import PriceCache
from .interface import MarketDataSource, PricingUnavailableError, UnknownSymbolError
from .symbols import normalize_symbol

logger = logging.getLogger(__name__)


class MassiveDataSource(MarketDataSource):
    """MarketDataSource backed by the Massive (Polygon.io) REST API.

    Polls the stocks snapshot endpoint for all watched tickers in a single
    API call, then writes results to the PriceCache.

    Rate limits:
      - Free tier: 5 req/min -> poll every 15 s (default)
      - Paid tiers: higher   -> poll every 2-5 s
    """

    def __init__(
        self,
        api_key: str,
        price_cache: PriceCache,
        poll_interval: float = 15.0,
    ) -> None:
        self._api_key = api_key
        self._cache = price_cache
        self._interval = poll_interval
        self._tickers: list[str] = []
        self._task: asyncio.Task | None = None
        self._client: RESTClient | None = None

    async def start(self, tickers: list[str]) -> None:
        self._client = RESTClient(api_key=self._api_key)
        self._tickers = list(tickers)
        await self._poll_once()          # immediate first poll — cache is warm on return
        self._task = asyncio.create_task(self._poll_loop(), name="massive-poller")
        logger.info(
            "Massive poller started: %d tickers, %.1fs interval",
            len(tickers), self._interval,
        )

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._client = None
        logger.info("Massive poller stopped")

    async def add_ticker(self, ticker: str) -> None:
        symbol = normalize_symbol(ticker)
        if symbol not in self._tickers:
            self._tickers.append(symbol)
            logger.info("Massive: added %s (appears on next poll)", symbol)

    async def remove_ticker(self, ticker: str) -> None:
        symbol = normalize_symbol(ticker)
        self._tickers = [t for t in self._tickers if t != symbol]
        self._cache.remove(symbol)
        logger.info("Massive: removed ticker %s", symbol)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    # change required — new method
    async def ensure_priced(self, ticker: str, timeout: float = 5.0) -> float:
        """Fetch a single symbol on demand rather than waiting for the next poll.

        Only joins the polled set *after* a price is confirmed, so a failed
        lookup leaves no residue to roll back.
        """
        symbol = normalize_symbol(ticker)

        cached = self._cache.get_price(symbol)
        if cached is not None and symbol in self._tickers:
            return cached

        if self._client is None:
            raise PricingUnavailableError("Market data source is not running")

        try:
            snapshot = await asyncio.wait_for(
                asyncio.to_thread(self._fetch_one, symbol), timeout=timeout
            )
        except asyncio.TimeoutError as exc:
            raise PricingUnavailableError(
                f"Timed out fetching a price for {symbol}"
            ) from exc
        except Exception as exc:
            # 404 / empty result = unknown symbol; anything else is transient.
            if _is_not_found(exc):
                raise UnknownSymbolError(f"{symbol} is not a recognized symbol") from exc
            raise PricingUnavailableError(
                f"Could not fetch a price for {symbol}: {exc}"
            ) from exc

        price = getattr(getattr(snapshot, "last_trade", None), "price", None)
        if price is None:
            raise UnknownSymbolError(f"No trade data available for {symbol}")

        timestamp = snapshot.last_trade.timestamp / 1000.0
        self._cache.update(ticker=symbol, price=price, timestamp=timestamp)

        # Success — now (and only now) join the polled set.
        if symbol not in self._tickers:
            self._tickers.append(symbol)

        return round(price, 2)

    # --- Internal ---

    async def _poll_loop(self) -> None:
        """Poll on interval. The first poll already happened in start()."""
        while True:
            await asyncio.sleep(self._interval)
            await self._poll_once()

    async def _poll_once(self) -> None:
        """One poll cycle: fetch snapshots, update cache. Never raises."""
        if not self._tickers or not self._client:
            return

        try:
            # The Massive RESTClient is synchronous — run it off the event loop.
            snapshots = await asyncio.to_thread(self._fetch_snapshots)
            processed = 0
            for snap in snapshots:
                try:
                    price = snap.last_trade.price
                    timestamp = snap.last_trade.timestamp / 1000.0  # ms -> s
                    self._cache.update(ticker=snap.ticker, price=price, timestamp=timestamp)
                    processed += 1
                except (AttributeError, TypeError) as e:
                    logger.warning(
                        "Skipping snapshot for %s: %s", getattr(snap, "ticker", "???"), e
                    )
            logger.debug("Massive poll: updated %d/%d tickers", processed, len(self._tickers))

        except Exception as e:
            # Common: 401 bad key, 429 rate limit, network blips.
            # Don't re-raise — the loop retries on the next interval.
            logger.error("Massive poll failed: %s", e)

    def _fetch_snapshots(self) -> list:
        """Synchronous batch call. Runs in a worker thread."""
        return self._client.get_snapshot_all(
            market_type=SnapshotMarketType.STOCKS,
            tickers=self._tickers,
        )

    def _fetch_one(self, symbol: str):
        """Synchronous single-ticker call. Runs in a worker thread."""
        return self._client.get_snapshot_ticker(
            market_type=SnapshotMarketType.STOCKS,
            ticker=symbol,
        )


def _is_not_found(exc: Exception) -> bool:
    """Best-effort classification of 'symbol does not exist' vs. transient failure."""
    status = getattr(exc, "status", None) or getattr(exc, "status_code", None)
    if status in (400, 404):
        return True
    return "not found" in str(exc).lower()
```

### 9.3 Poll-interval guidance

| Tier | Limit | `poll_interval` | Calls/min |
|---|---|---|---|
| Free | 5 req/min | `15.0` (default) | 4 |
| Starter / paid | effectively unlimited | `5.0` | 12 |
| Advanced | unlimited | `2.0` | 30 |

`ensure_priced` spends one extra call, so the free-tier default leaves a call of headroom per minute on purpose.

### 9.4 Market-hours behaviour

Outside regular trading hours `last_trade.price` is the last print (possibly after-hours), so prices simply stop moving. This is correct and needs no special handling — but it is exactly why the SSE contract must re-emit `"flat"` ticks (§11) rather than falling silent, so the frontend keeps rendering and the connection indicator stays green.

---

## 10. Factory — `factory.py`

**As built.** One environment variable decides everything.

```python
"""Factory for creating market data sources."""

from __future__ import annotations

import logging
import os

from .cache import PriceCache
from .interface import MarketDataSource
from .massive_client import MassiveDataSource
from .simulator import SimulatorDataSource

logger = logging.getLogger(__name__)


def create_market_data_source(price_cache: PriceCache) -> MarketDataSource:
    """Select the data source from the environment.

    - MASSIVE_API_KEY set and non-empty -> MassiveDataSource (real data)
    - Otherwise                         -> SimulatorDataSource (GBM)

    Returns an unstarted source; the caller must await source.start(tickers).
    """
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()

    if api_key:
        poll_interval = float(os.environ.get("MASSIVE_POLL_INTERVAL", "15.0"))
        logger.info("Market data source: Massive API (poll every %.1fs)", poll_interval)
        return MassiveDataSource(
            api_key=api_key, price_cache=price_cache, poll_interval=poll_interval
        )

    logger.info("Market data source: GBM Simulator")
    return SimulatorDataSource(price_cache=price_cache)
```

`MASSIVE_POLL_INTERVAL` (**change required**, optional) lets a paid-tier user drop to 2-5 s without a code change. Absent, it defaults to the free-tier-safe 15 s.

Both imports are at module level. `massive` is a declared core dependency, so lazy-importing it bought nothing and broke `unittest.mock.patch` targets in tests.

---

## 11. SSE Streaming — `stream.py`

### 11.1 The contract gap

PLAN §6 promises: *"The stream re-emits every priced ticker each tick, including unchanged ones (`flat`)."* The shipped generator instead gates on `PriceCache.version` and only yields when the cache changed. In simulator mode that's invisible (the cache changes every 500 ms). In **Massive mode it means the stream emits nothing for 15 seconds at a time** — the frontend can't distinguish a quiet market from a dead connection, and `REVIEW.md` flags it as a P1 contract break.

Second, subtler problem: `PriceUpdate.direction` is relative to the last *cache write*. Re-emitting a cached update between Massive polls would repeat `"up"` every tick, and the frontend would flash the row green twice a second for 15 seconds on a single real uptick.

**Resolution — emit unconditionally, compute direction per connection.** Every `interval`, send a snapshot of every priced ticker. Each connection remembers the last price it sent for each ticker and derives `direction`/`change` against *that*, so `direction` answers exactly the question the frontend asks: "did this change since the last event I received?" A ticker that didn't move reports `"flat"` with `change: 0.0` and triggers no animation.

### 11.2 Payload

```
retry: 1000

data: {"seq":41,"ts":1738012800.5,"prices":{
  "AAPL":{"ticker":"AAPL","price":190.52,"previous_price":190.48,"change":0.04,
          "change_percent":0.021,"direction":"up","timestamp":1738012800.4},
  "JPM": {"ticker":"JPM","price":195.10,"previous_price":195.10,"change":0.0,
          "change_percent":0.0,"direction":"flat","timestamp":1738012788.1}}}
```

- The envelope (`seq`, `ts`, `prices`) is extensible; a bare ticker-keyed map is not, because any new top-level key could collide with a symbol.
- `seq` increments per connection, so a client can detect gaps and the dev tools show liveness at a glance.
- `previous_price` is the last price *this connection* was sent — which is what makes `change` and `direction` internally consistent for animation.
- Default event type (no `event:` line), so the frontend uses plain `EventSource.onmessage`.
- Emitting every 500 ms doubles as the keepalive; no separate heartbeat comment is needed.

### 11.3 Implementation

**Change required** — replaces the version-gated generator.

```python
"""SSE streaming endpoint for live price updates."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache

logger = logging.getLogger(__name__)


def create_stream_router(price_cache: PriceCache, interval: float = 0.5) -> APIRouter:
    """Build the SSE router bound to a PriceCache.

    A fresh APIRouter per call (previously module-level) so the route can't be
    registered twice when tests build more than one app.
    """
    router = APIRouter(prefix="/api/stream", tags=["streaming"])

    @router.get("/prices")
    async def stream_prices(request: Request) -> StreamingResponse:
        """Live price stream. Connect with `new EventSource('/api/stream/prices')`."""
        return StreamingResponse(
            _generate_events(price_cache, request, interval),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering if proxied
            },
        )

    return router


def _diff(ticker: str, price: float, last: float | None, timestamp: float) -> dict:
    """Build one ticker's payload relative to the last price THIS connection sent."""
    previous = price if last is None else last
    change = round(price - previous, 4)
    if change > 0:
        direction = "up"
    elif change < 0:
        direction = "down"
    else:
        direction = "flat"
    return {
        "ticker": ticker,
        "price": price,
        "previous_price": previous,
        "change": change,
        "change_percent": round(change / previous * 100, 4) if previous else 0.0,
        "direction": direction,
        "timestamp": timestamp,
    }


async def _generate_events(
    price_cache: PriceCache,
    request: Request,
    interval: float = 0.5,
) -> AsyncGenerator[str, None]:
    """Yield an SSE event every `interval` seconds for every priced ticker.

    Emits unconditionally — unchanged tickers are reported as 'flat'. This keeps
    the stream alive between Massive polls and lets the client treat silence as
    a genuine connection problem.
    """
    yield "retry: 1000\n\n"

    client_ip = request.client.host if request.client else "unknown"
    logger.info("SSE client connected: %s", client_ip)

    last_sent: dict[str, float] = {}
    seq = 0

    try:
        while True:
            if await request.is_disconnected():
                logger.info("SSE client disconnected: %s", client_ip)
                break

            snapshot = price_cache.get_all()
            prices = {
                ticker: _diff(ticker, u.price, last_sent.get(ticker), u.timestamp)
                for ticker, u in snapshot.items()
            }
            # Forget tickers that left the priced set, so a re-add starts flat.
            last_sent = {ticker: u.price for ticker, u in snapshot.items()}

            if prices:
                seq += 1
                payload = json.dumps({"seq": seq, "ts": time.time(), "prices": prices})
                yield f"data: {payload}\n\n"

            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("SSE stream cancelled for: %s", client_ip)
        raise
```

### 11.4 Client usage

```javascript
const es = new EventSource("/api/stream/prices");

es.onmessage = (event) => {
  const { prices } = JSON.parse(event.data);
  for (const [ticker, update] of Object.entries(prices)) {
    setPrice(ticker, update.price);
    if (update.direction !== "flat") flash(ticker, update.direction);  // green/red, fades ~500ms
    appendSparklinePoint(ticker, update.price, update.timestamp);
  }
};

es.onerror = () => setConnectionStatus("reconnecting");  // EventSource retries automatically
es.onopen  = () => setConnectionStatus("connected");
```

There is no `Last-Event-ID` replay (PLAN §6): a reconnecting client resumes from the live cache, and ticks missed during the gap are gone. Sparklines therefore show a small gap after a reconnect, which is acceptable — the series is a session-lifetime visual, not a record.

---

## 12. FastAPI Lifecycle Integration

The market data source starts in the app lifespan, *after* DB init (PLAN §7 requires the schema to exist before the market task runs) and before any request is served.

```python
"""app/main.py — market data wiring."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import get_open_position_tickers, get_watchlist_tickers, init_db
from app.market import PriceCache, create_market_data_source, create_stream_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Schema + seed data must exist before anything reads the DB
    init_db()

    # 2. Priced set = watchlist ∪ open positions (PLAN §6)
    tickers = sorted(set(get_watchlist_tickers()) | set(get_open_position_tickers()))

    # 3. Start the market data source
    cache = PriceCache()
    source = create_market_data_source(cache)
    await source.start(tickers)

    # 4. Publish on app.state for route dependencies
    app.state.price_cache = cache
    app.state.market_source = source

    try:
        yield
    finally:
        await source.stop()


app = FastAPI(lifespan=lifespan)
app.include_router(create_stream_router(app.state.price_cache))
```

> The router needs the cache, which is created inside `lifespan`. Either build the cache at module scope and pass the same instance into `lifespan`, or register the router inside `lifespan` before `yield`. The former is simpler; `PriceCache()` has no I/O and is safe to construct at import time.

Dependencies for other routers:

```python
from fastapi import Depends, Request

def get_price_cache(request: Request) -> PriceCache:
    return request.app.state.price_cache

def get_market_source(request: Request) -> MarketDataSource:
    return request.app.state.market_source
```

---

## 13. Watchlist & Trade Coordination

### 13.1 Add to watchlist

Validate and price *first*, write the DB row only on success — so a rejected symbol never leaves a row behind.

```python
@router.post("/api/watchlist")
async def add_to_watchlist(
    payload: WatchlistAdd,
    source: MarketDataSource = Depends(get_market_source),
):
    try:
        symbol = normalize_symbol(payload.ticker)
        price = await source.ensure_priced(symbol)
    except (InvalidSymbolFormatError, UnknownSymbolError) as e:
        raise HTTPException(400, str(e))
    except PricingUnavailableError as e:
        raise HTTPException(503, str(e))

    db.insert_watchlist_entry(symbol)   # UNIQUE(user_id, ticker) makes this idempotent
    return {"ticker": symbol, "price": price}
```

### 13.2 Remove from watchlist

Only stop pricing if no position remains — the priced set is `watchlist ∪ positions`.

```python
@router.delete("/api/watchlist/{ticker}")
async def remove_from_watchlist(
    ticker: str,
    source: MarketDataSource = Depends(get_market_source),
):
    symbol = normalize_symbol(ticker)
    db.delete_watchlist_entry(symbol)

    position = db.get_position(symbol)
    if position is None or position.quantity == 0:
        await source.remove_ticker(symbol)   # otherwise keep pricing it for valuation

    return {"status": "ok"}
```

### 13.3 Trade execution

This is the flow `REVIEW.md` asked us to pin down. The fill price comes from the cache; an unpriced ticker is auto-added; an unrecognized symbol is rejected — and now each of those has one implementable meaning in both modes.

```python
@router.post("/api/portfolio/trade")
async def execute_trade(
    order: TradeRequest,                       # {ticker, quantity, side}
    source: MarketDataSource = Depends(get_market_source),
):
    if order.quantity <= 0:
        raise HTTPException(400, "Quantity must be positive")

    # 1. Resolve a fill price. Adds the ticker to the priced set on success only.
    try:
        symbol = normalize_symbol(order.ticker)
        price = await source.ensure_priced(symbol, timeout=5.0)
    except (InvalidSymbolFormatError, UnknownSymbolError) as e:
        raise HTTPException(400, str(e))       # permanent — don't retry
    except PricingUnavailableError as e:
        raise HTTPException(503, str(e))       # transient — retry is reasonable

    # 2. Whole-order validation (no partial fills)
    cost = order.quantity * price
    if order.side == "buy" and cost > db.get_cash_balance():
        raise HTTPException(400, f"Insufficient cash: need ${cost:,.2f}")
    if order.side == "sell" and order.quantity > db.get_position_quantity(symbol):
        raise HTTPException(400, f"Insufficient shares of {symbol}")

    # 3. Execute, then persist the watchlist membership implied by step 1
    trade = db.execute_trade(symbol, order.side, order.quantity, price)
    db.ensure_watchlist_entry(symbol)
    db.record_portfolio_snapshot()

    return trade
```

**Rollback semantics (the open question in `REVIEW.md`).** There is nothing to roll back: `ensure_priced` joins the ticker to the polled set only after a price is confirmed, and the watchlist row is written only after the trade succeeds. A failed lookup leaves the watchlist, the polled set, and the cache exactly as they were.

**Timeout budget.** 5 s is one Massive round trip with slack, well under a browser's patience. In simulator mode `ensure_priced` returns without awaiting I/O at all.

### 13.4 LLM-issued trades

PLAN §9 requires LLM trades to go through identical validation. Call the same service function the route calls — not the HTTP route — and translate raised errors into the `actions.errors` array of the chat response:

```python
for t in llm_response.trades:
    try:
        executed.append(await trade_service.execute(t.ticker, t.side, t.quantity))
    except (UnknownSymbolError, InvalidSymbolFormatError, ValidationError) as e:
        errors.append(str(e))
    except PricingUnavailableError as e:
        errors.append(f"{t.ticker}: {e}")
```

---

## 14. Error Handling & Edge Cases

**14.1 Empty watchlist at startup.** `start([])` is valid. The simulator's `step()` returns `{}`; the Massive poller skips its API call. The SSE loop yields nothing until a ticker exists (the `if prices:` guard), then resumes. Adding a ticker recovers immediately.

**14.2 Invalid Massive API key.** The first poll fails with 401, is logged, and the loop keeps retrying. The cache stays empty, so SSE emits nothing and the UI shows a connected-but-empty terminal. **Change required:** count consecutive poll failures and log an escalated `ERROR` after 3, naming 401 explicitly — a silent empty grid is the single most confusing failure mode in this app. Surfacing this through `/api/health` is a reasonable follow-on.

**14.3 Rate limiting (429).** Caught by the same handler and retried on the next interval. The batch snapshot endpoint means ticker count doesn't affect call count, so a user adding 30 tickers cannot trip the limit — only a too-short `MASSIVE_POLL_INTERVAL` can.

**14.4 Malformed snapshot.** A snapshot missing `last_trade` raises `AttributeError`/`TypeError`, is logged per ticker, and skipped; other tickers in the same batch still update.

**14.5 Trade against a stale price.** In Massive mode the cached price can be up to `poll_interval` old. This is accepted: no fees, no slippage, fake money. Worth stating in the UI as "prices delayed up to 15 s" when a key is configured.

**14.6 Non-PSD correlation matrix.** If someone widens the correlation constants, `np.linalg.cholesky` raises `LinAlgError` and — inside `_rebuild_cholesky`, called from `add_ticker` — would propagate into a request. **Change required:** fall back to uncorrelated draws rather than failing the request.

```python
# _rebuild_cholesky(), replacing the bare decomposition:
try:
    self._cholesky = np.linalg.cholesky(corr)
except np.linalg.LinAlgError:
    logger.warning("Correlation matrix not positive semi-definite; using independent draws")
    self._cholesky = None
```

**14.7 Cache miss on a held position.** Shouldn't happen — startup unions positions into the priced set (§12). If it does (e.g., a Massive symbol that stopped returning trades), portfolio valuation must treat the position as `None`-priced and exclude it from `total_value` rather than valuing it at zero, which would show a fake catastrophic loss.

**14.8 Lock contention.** At 10 tickers × 2 Hz, plus one `get_all()` per SSE client per tick, the critical section is a dict copy of ~10 entries. Negligible. A read-write lock would be the fix if this ever mattered; it won't at this scale.

**14.9 Clock source for `timestamp`.** Simulator timestamps come from `time.time()` (wall clock); Massive timestamps come from the exchange. Both are Unix seconds, so the frontend can plot them on one axis, but Massive timestamps can appear slightly stale relative to local time. Don't compute "data age" by subtracting them from `Date.now()` and alarming the user.

---

## 15. Testing Strategy

73 tests exist and pass. The additions below cover the new behaviour in this document.

### 15.1 Existing coverage

| Module | Tests | Coverage |
|---|---|---|
| `test_models.py` | 11 | 100% |
| `test_cache.py` | 13 | 100% |
| `test_simulator.py` | 17 | 98% |
| `test_simulator_source.py` | 10 | integration |
| `test_factory.py` | 7 | 100% |
| `test_massive.py` | 13 | 56% (API methods mocked) |

### 15.2 New: symbol validation

```python
import pytest
from app.market.symbols import InvalidSymbolFormatError, is_simulated, normalize_symbol


@pytest.mark.parametrize("raw,expected", [
    ("aapl", "AAPL"), ("  MSFT  ", "MSFT"), ("brk.b", "BRK.B"), ("V", "V"),
])
def test_normalize_accepts_valid(raw, expected):
    assert normalize_symbol(raw) == expected


@pytest.mark.parametrize("raw", ["NOT_A_STOCK", "", "   ", "TOOLONG", "AA PL", "12345", None])
def test_normalize_rejects_invalid(raw):
    with pytest.raises(InvalidSymbolFormatError):
        normalize_symbol(raw)


def test_universe_membership():
    assert is_simulated("AAPL")
    assert not is_simulated("ZZZZ")   # valid shape, not a real company
```

### 15.3 New: `ensure_priced`

```python
@pytest.mark.asyncio
async def test_simulator_ensure_priced_adds_and_returns():
    cache = PriceCache()
    source = SimulatorDataSource(price_cache=cache, update_interval=0.05)
    await source.start(["AAPL"])

    price = await source.ensure_priced("pypl")     # normalizes, in universe
    assert price > 0
    assert cache.get_price("PYPL") == price
    assert "PYPL" in source.get_tickers()

    await source.stop()


@pytest.mark.asyncio
async def test_simulator_ensure_priced_rejects_unknown():
    cache = PriceCache()
    source = SimulatorDataSource(price_cache=cache)
    await source.start(["AAPL"])

    with pytest.raises(UnknownSymbolError):
        await source.ensure_priced("ZZZZ")
    assert "ZZZZ" not in source.get_tickers()      # no residue
    assert cache.get_price("ZZZZ") is None

    await source.stop()


@pytest.mark.asyncio
async def test_massive_ensure_priced_does_not_add_on_failure():
    cache = PriceCache()
    source = MassiveDataSource(api_key="k", price_cache=cache, poll_interval=60.0)
    source._client = MagicMock()

    with patch.object(source, "_fetch_one", side_effect=TimeoutError("slow")):
        with pytest.raises(PricingUnavailableError):
            await source.ensure_priced("AAPL", timeout=0.1)

    assert source.get_tickers() == []               # rollback-free by construction
```

### 15.4 New: SSE contract

The highest-value gap — `stream.py` sat at 31% coverage with no dedicated tests, and it is the frontend's entire contract.

```python
@pytest.mark.asyncio
async def test_stream_emits_flat_when_cache_is_static():
    """The Massive-mode case: no cache writes must still produce events."""
    cache = PriceCache()
    cache.update("AAPL", 190.00)

    app = FastAPI()
    app.include_router(create_stream_router(cache, interval=0.01))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        async with client.stream("GET", "/api/stream/prices") as response:
            events = [line async for line in _take(response.aiter_lines(), 6)]

    payloads = [json.loads(line[6:]) for line in events if line.startswith("data: ")]
    assert len(payloads) >= 2                                   # kept streaming
    assert payloads[1]["prices"]["AAPL"]["direction"] == "flat"  # no phantom flash
    assert payloads[1]["seq"] == payloads[0]["seq"] + 1


@pytest.mark.asyncio
async def test_stream_reports_direction_since_last_event():
    cache = PriceCache()
    cache.update("AAPL", 190.00)
    # ... first event, then cache.update("AAPL", 191.00) ...
    # second event must report direction 'up', previous_price 190.00, change 1.00
```

### 15.5 New: cache thread safety

```python
def test_concurrent_writes_are_consistent():
    cache = PriceCache()
    def writer(n):
        for i in range(1000):
            cache.update(f"T{n}", 100.0 + i)

    threads = [Thread(target=writer, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert cache.version == 8000
    assert len(cache) == 8
```

### 15.6 New: full default watchlist Cholesky

```python
def test_cholesky_succeeds_for_all_default_tickers():
    sim = GBMSimulator(tickers=list(SEED_PRICES))
    assert sim._cholesky is not None
    prices = sim.step()
    assert len(prices) == 10 and all(p > 0 for p in prices.values())
```

### 15.7 E2E hooks (`test/`)

- Fresh start: 10 tickers appear with prices within 2 s.
- Prices visibly change over 5 s (simulator mode).
- SSE resilience: kill the connection, confirm `EventSource` reconnects and prices resume.
- Add `PYPL` via the trade bar with no prior watchlist entry → position appears, ticker joins the watchlist.
- Trade `NOT_A_STOCK` → 400 with a readable message, no watchlist row created.

---

## 16. Configuration Summary

| Parameter | Location | Default | Description |
|---|---|---|---|
| `MASSIVE_API_KEY` | env | `""` | Non-empty → Massive API; otherwise simulator |
| `MASSIVE_POLL_INTERVAL` | env | `15.0` s | Poll cadence; lower it on paid tiers |
| `update_interval` | `SimulatorDataSource.__init__` | `0.5` s | Simulator tick |
| `poll_interval` | `MassiveDataSource.__init__` | `15.0` s | Massive poll |
| `event_probability` | `GBMSimulator.__init__` | `0.001` | Shock chance per ticker per tick |
| `dt` | `GBMSimulator.__init__` | `~8.48e-8` | GBM step (fraction of trading year) |
| `interval` | `create_stream_router` | `0.5` s | SSE emit cadence |
| retry directive | `_generate_events` | `1000` ms | EventSource reconnect delay |
| `timeout` | `ensure_priced` | `5.0` s | On-demand price fetch budget |

---

## 17. Delta From the Shipped Code

Everything an implementing agent needs to change, in dependency order.

| # | Change | Files | Closes |
|---|---|---|---|
| 1 | Add `symbols.py`: `normalize_symbol`, `SIMULATED_UNIVERSE`, `is_simulated` | `symbols.py` (new) | REVIEW P2 "source-independent ticker validation" |
| 2 | Add `UnknownSymbolError` / `PricingUnavailableError` and the `ensure_priced` abstract method | `interface.py` | REVIEW P1 "unpriced Massive ticker fill" |
| 3 | Implement `ensure_priced` in both sources; normalize symbols in `add_ticker`/`remove_ticker` | `simulator.py`, `massive_client.py` | same |
| 4 | Rewrite the SSE generator: emit every tick, per-connection direction, `{seq, ts, prices}` envelope; build a fresh `APIRouter` per call | `stream.py` | REVIEW P1 "SSE cadence"; MARKET_DATA_REVIEW §3.6 |
| 5 | Lock the `version` property | `cache.py` | MARKET_DATA_REVIEW §3.4 |
| 6 | Fall back to independent draws on `LinAlgError` | `simulator.py` | §14.6 |
| 7 | Read `MASSIVE_POLL_INTERVAL` from env | `factory.py` | §9.3 |
| 8 | Escalate repeated Massive poll failures to `ERROR` after 3 consecutive | `massive_client.py` | §14.2 |
| 9 | Add tests: symbols, `ensure_priced`, SSE contract, cache concurrency, full-watchlist Cholesky | `tests/market/` | MARKET_DATA_REVIEW §4.2 |

Items 1-4 are prerequisites for the portfolio and chat work: the trade route cannot be written without `ensure_priced`, and the frontend cannot be written against a stream whose cadence is undefined. Items 5-8 are independent hardening and can land any time.

`PriceUpdate`, `PriceCache`, `GBMSimulator`, the factory's selection logic, and the Massive polling loop are unchanged.
