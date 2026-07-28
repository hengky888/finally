# Market Data — Interface Contracts

The types, classes, methods, and errors that make up the market data subsystem's public contract. Everything here is source-agnostic: it holds identically whether prices come from the GBM simulator or the Massive REST API.

Architecture and wiring are in [`market_data_design.md`](market_data_design.md). Implementations are in [`market_simulator.md`](market_simulator.md) and [`massive_api.md`](massive_api.md).

Snippets are labelled **as built** or **change required**.

---

## Table of Contents

1. [Data Model — `models.py`](#1-data-model--modelspy)
2. [Price Cache — `cache.py`](#2-price-cache--cachepy)
3. [Unified Interface — `interface.py`](#3-unified-interface--interfacepy)
4. [Error Taxonomy & HTTP Mapping](#4-error-taxonomy--http-mapping)
5. [Factory — `factory.py`](#5-factory--factorypy)
6. [Public API — `__init__.py`](#6-public-api--__init__py)
7. [Conformance & Cache Testing](#7-conformance--cache-testing)

---

## 1. Data Model — `models.py`

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

> **Note on `direction`.** `PriceUpdate.direction` is relative to the previous *cache write*. That is not the same as "changed since the last SSE event the client saw" — in Massive mode, the cached update sits unchanged between polls, still reporting `"up"` from the last poll. [`market_data_design.md` §3](market_data_design.md#3-sse-streaming--streampy) explains why the SSE layer computes its own per-connection direction rather than forwarding this one.

---

## 2. Price Cache — `cache.py`

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

**On `version`.** The counter remains useful for diagnostics and tests, but it is no longer the SSE emit gate — the stream emits unconditionally. See [`market_data_design.md` §3.1](market_data_design.md#31-the-contract-gap).

---

## 3. Unified Interface — `interface.py`

The ABC every data source implements. Five methods are **as built**; `ensure_priced` is **change required** and is the heart of trade execution.

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

### Expected behaviour of each method

| Method | Blocking? | Guarantees on return | Failure mode |
|---|---|---|---|
| `start(tickers)` | yes | Background task running; cache warm for the given tickers | Never called twice; behaviour undefined if it is |
| `stop()` | yes | Background task cancelled, resources released | Idempotent — safe to call after a failed `start` |
| `add_ticker(t)` | no (fire-and-forget) | Ticker is in the active set; **a price may not exist yet** | Silent no-op if already present |
| `remove_ticker(t)` | yes | Ticker gone from the active set *and* the cache | Silent no-op if absent |
| `get_tickers()` | n/a (sync) | Current active set as a new list | — |
| `ensure_priced(t, timeout)` | yes | A price is in the cache and returned; ticker joined the active set | Raises `UnknownSymbolError` / `PricingUnavailableError`; **no residue on failure** |

### Why `ensure_priced` exists

`add_ticker` is deliberately fire-and-forget: the watchlist UI doesn't need to block, and in Massive mode a new ticker simply appears on the next poll. But PLAN §8 requires a trade in an unpriced ticker to auto-add it and fill *at execution time*. In Massive mode `add_ticker` can leave the caller waiting up to 15 seconds for a price that may never come (bad symbol). `ensure_priced` is the synchronous, fallible counterpart: it either returns a price you can fill against or raises a typed error the route maps to a status code. This closes the `REVIEW.md` finding "Define how an unpriced Massive ticker gets a fill price".

The **no-residue** guarantee is what makes rollback unnecessary at the route layer: a source must not leave a ticker in its active set, in the cache, or in the watchlist if `ensure_priced` raised. Both implementations achieve this by construction rather than by compensating writes.

---

## 4. Error Taxonomy & HTTP Mapping

Three error types cover every rejection path. Routes map them to status codes without inspecting messages.

| Error | Defined in | Meaning | HTTP | Retry? |
|---|---|---|---|---|
| `InvalidSymbolFormatError` | `symbols.py` (see [`market_simulator.md` §5](market_simulator.md#5-symbol-validation--symbolspy)) | The string cannot be a ticker at all (`NOT_A_STOCK`, `""`, `AA PL`) | 400 | No |
| `UnknownSymbolError` | `interface.py` | Well-formed, but this source cannot price it | 400 | No |
| `PricingUnavailableError` | `interface.py` | Valid symbol, no price obtainable right now (timeout, rate limit, network, source not running) | 503 | Yes |

`InvalidSymbolFormatError` subclasses `ValueError` and is raised by `normalize_symbol`, which runs *before* either the data source or the watchlist table is mutated. The two source-level errors are raised from `ensure_priced`. Route-level handling is shown in [`market_data_design.md` §5](market_data_design.md#5-watchlist--trade-coordination).

---

## 5. Factory — `factory.py`

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

## 6. Public API — `__init__.py`

The rest of the backend never reaches into submodules:

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

Downstream usage:

```python
from app.market import PriceCache, create_market_data_source

# Startup
cache = PriceCache()
source = create_market_data_source(cache)  # Reads MASSIVE_API_KEY
await source.start(["AAPL", "GOOGL", "MSFT", ...])

# Read prices
update = cache.get("AAPL")          # PriceUpdate or None
price = cache.get_price("AAPL")     # float or None
all_prices = cache.get_all()        # dict[str, PriceUpdate]

# Dynamic watchlist
await source.add_ticker("TSLA")
await source.remove_ticker("GOOGL")

# Shutdown
await source.stop()
```

---

## 7. Conformance & Cache Testing

Both implementations must satisfy the same contract, so the behavioural assertions in §3 are the ones worth testing against each source in turn — in particular the no-residue guarantee on `ensure_priced` failure. The per-source tests are in [`market_simulator.md` §10](market_simulator.md#10-testing) and [`massive_api.md` §8](massive_api.md#8-testing).

### Cache thread safety (new)

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
