# Market Data Backend — Detailed Design

Implementation-ready design of record for the FinAlly market data subsystem: the unified data-source API, the GBM simulator, the Massive REST client, the shared price cache, the SSE streaming endpoint, and the FastAPI wiring that ties them to the watchlist and trade routes.

Everything described here lives under `backend/app/market/`.

**Status.** This subsystem is built and shipped. Every code snippet below is the real implementation, not a sketch — 127 tests pass at 97% statement coverage. Where a design choice has a non-obvious reason, the reason is given inline; where an alternative was rejected, it says so.

This document supersedes and consolidates the four split documents (`market_interface.md`, `market_simulator.md`, `massive_api.md`, and the earlier architecture doc now in [`archive/`](archive/)). Read this one first; the split documents remain useful only for their per-component test plans.

---

## Table of Contents

1. [Architecture](#1-architecture)
2. [File Structure & Public API](#2-file-structure--public-api)
3. [Data Model — `models.py`](#3-data-model--modelspy)
4. [Price Cache — `cache.py`](#4-price-cache--cachepy)
5. [Unified Interface — `interface.py`](#5-unified-interface--interfacepy)
6. [Symbol Validation — `symbols.py`](#6-symbol-validation--symbolspy)
7. [Market Simulator — `simulator.py`](#7-market-simulator--simulatorpy)
8. [Massive API Client — `massive_client.py`](#8-massive-api-client--massive_clientpy)
9. [Factory — `factory.py`](#9-factory--factorypy)
10. [SSE Streaming — `stream.py`](#10-sse-streaming--streampy)
11. [FastAPI Lifecycle Integration](#11-fastapi-lifecycle-integration)
12. [Watchlist & Trade Coordination](#12-watchlist--trade-coordination)
13. [Error Handling & Edge Cases](#13-error-handling--edge-cases)
14. [Configuration](#14-configuration)
15. [Testing](#15-testing)

---

## 1. Architecture

One abstract interface, two implementations, one shared cache. Every consumer downstream of the cache is source-agnostic — nothing outside `app/market/` knows or cares whether prices come from Geometric Brownian Motion or from a real exchange feed.

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

The two sources differ in almost every respect — one is synchronous and authoritative, the other is network-bound and fallible; one ticks twice a second, the other every 15 seconds — but they converge on the same five-method contract plus `ensure_priced`, and they write to the same cache in the same shape. That convergence is the whole design.

### Invariants the rest of the backend can rely on

1. **The cache is written only by the active data source.** Everyone else reads. There is no second writer, no cache invalidation protocol, no staleness bookkeeping.
2. **The priced set is `watchlist ∪ open positions`** (PLAN §6). A held ticker stays priced after leaving the watchlist, so the portfolio can always be valued.
3. **A ticker present in the cache always has a usable, non-negative fill price.** GBM is multiplicative through `exp()`, so simulated prices cannot go non-positive; Massive prices come from actual trade prints.
4. **Background loops never raise.** A failed tick or poll is logged and retried. A dead background task means prices silently freeze, which is the worst failure mode this app has — worse than stale prices, because it is invisible.
5. **`ensure_priced` leaves no residue on failure.** A rejected symbol never joins the active set, the cache, or the watchlist. This is achieved by ordering, not by compensating writes — see [§5](#5-unified-interface--interfacepy).

### Why push-to-cache instead of pull-from-source

The sources push into the cache on their own schedule; consumers read from the cache on theirs. This decouples three unrelated cadences — simulator 500 ms, Massive 15 s, SSE 500 ms — that would otherwise have to know about each other. The SSE layer never asks "which source is active?" or "when is the next poll?"; it reads a dict and emits.

The alternative (SSE awaiting a source-level notification) was rejected because it couples emit cadence to source cadence. In Massive mode that would produce one event every 15 seconds, and the frontend would have no way to distinguish a quiet market from a dead connection. See [§10.1](#101-why-the-stream-emits-unconditionally).

---

## 2. File Structure & Public API

```
backend/app/market/
├── __init__.py           # Public re-exports
├── models.py             # PriceUpdate dataclass
├── cache.py              # PriceCache (thread-safe store)
├── interface.py          # MarketDataSource ABC + error types
├── symbols.py            # Symbol normalization + simulated universe
├── seed_prices.py        # SEED_PRICES, TICKER_PARAMS, correlation config
├── simulator.py          # GBMSimulator + SimulatorDataSource
├── massive_client.py     # MassiveDataSource
├── factory.py            # create_market_data_source()
└── stream.py             # SSE endpoint (FastAPI router factory)
```

The rest of the backend never reaches into submodules — everything it needs is re-exported:

```python
"""Market data subsystem for FinAlly.

Public API:
    PriceUpdate         - Immutable price snapshot dataclass
    PriceCache          - Thread-safe in-memory price store
    MarketDataSource    - Abstract interface for data providers
    UnknownSymbolError  - Permanent rejection of a symbol (HTTP 400)
    PricingUnavailableError - Transient pricing failure (HTTP 503)
    create_market_data_source - Factory that selects simulator or Massive
    create_stream_router - FastAPI router factory for SSE endpoint
    normalize_symbol     - Shape-validate and uppercase a user-supplied ticker
"""

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

### End-to-end usage

```python
from app.market import PriceCache, create_market_data_source

# --- Startup ---
cache = PriceCache()
source = create_market_data_source(cache)      # reads MASSIVE_API_KEY
await source.start(["AAPL", "GOOGL", "MSFT"])  # cache is warm on return

# --- Reading prices (portfolio valuation, trade fills) ---
update = cache.get("AAPL")        # PriceUpdate | None
price = cache.get_price("AAPL")   # float | None
snapshot = cache.get_all()        # dict[str, PriceUpdate]

# --- Dynamic watchlist ---
await source.add_ticker("TSLA")            # fire-and-forget, no price guaranteed
price = await source.ensure_priced("PYPL") # blocking, raises on failure
await source.remove_ticker("GOOGL")

# --- Shutdown ---
await source.stop()
```

`InvalidSymbolFormatError` is deliberately **not** re-exported from `app.market` — it lives in `app.market.symbols` and subclasses `ValueError`. Routes that want to catch it by name import it directly; routes that don't will still catch it via `ValueError`.

---

## 3. Data Model — `models.py`

`PriceUpdate` is the only type that leaves the market layer.

```python
"""Data models for market data."""

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
        """Percentage change from previous update."""
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

### Why it is shaped this way

- **`frozen=True`** — a `PriceUpdate` is a value object. Once created it never mutates, so it can be handed to any number of async readers without copying or defensive snapshots.
- **`slots=True`** — roughly 20 of these are created per second for the container's lifetime. Slots keeps the per-object footprint flat and the attribute access fast.
- **Derived properties, not stored fields** — `change`, `change_percent`, and `direction` are computed from `price` and `previous_price`, so they cannot drift out of sync with each other. An earlier draft stored `change` and `direction` as fields; that permits an update whose `direction` says `"up"` while its prices say otherwise.
- **`change_percent` guards division by zero** — a price of `0.0` is not reachable through GBM, but a malformed Massive snapshot could produce one, and a `ZeroDivisionError` inside a serialization path would take down an SSE connection.

### The one subtlety: what `previous_price` means

`previous_price` is **the previous write to the cache**, not the previous close and not "the last value the browser saw". Those are three different things:

| Question | Answered by |
|---|---|
| How much has this moved since the last cache write? | `PriceUpdate.direction` |
| How much has this moved since the last event *this browser* received? | the SSE layer's per-connection diff ([§10](#10-sse-streaming--streampy)) |
| How much has this moved today? | nothing yet — would need `day.previous_close` |

This matters most in Massive mode, where a cached update sits unchanged for 15 seconds while still reporting `"up"` from the last poll. Forwarding `PriceUpdate.direction` straight to the browser would flash a row green twice a second for the whole inter-poll gap on the strength of a single real uptick. [§10.1](#101-why-the-stream-emits-unconditionally) explains how the stream avoids this.

Day-over-day change is a deliberate omission. If the frontend needs it later, add a `previous_close` field populated from Massive's `day.previous_close` and defaulted to the session seed price in simulator mode.

---

## 4. Price Cache — `cache.py`

A `threading.Lock` guarding a plain dict. The lock is `threading.Lock` rather than `asyncio.Lock` because the Massive client writes from a real OS worker thread via `asyncio.to_thread`, while SSE readers run on the event loop — an asyncio primitive would not protect against the former.

```python
"""Thread-safe in-memory price cache."""

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
        self._version: int = 0  # Monotonically increasing; bumped on every update

    def update(self, ticker: str, price: float, timestamp: float | None = None) -> PriceUpdate:
        """Record a new price for a ticker. Returns the created PriceUpdate.

        Automatically computes direction and change from the previous price.
        If this is the first update for the ticker, previous_price == price (direction='flat').
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
        """Get the latest price for a single ticker, or None if unknown."""
        with self._lock:
            return self._prices.get(ticker)

    def get_all(self) -> dict[str, PriceUpdate]:
        """Snapshot of all current prices. Returns a shallow copy."""
        with self._lock:
            return dict(self._prices)

    def get_price(self, ticker: str) -> float | None:
        """Convenience: get just the price float, or None."""
        update = self.get(ticker)
        return update.price if update else None

    def remove(self, ticker: str) -> None:
        """Remove a ticker from the cache (e.g., when removed from watchlist)."""
        with self._lock:
            self._prices.pop(ticker, None)

    @property
    def version(self) -> int:
        """Current version counter. Useful for SSE change detection."""
        with self._lock:
            return self._version

    def __len__(self) -> int:
        with self._lock:
            return len(self._prices)

    def __contains__(self, ticker: str) -> bool:
        with self._lock:
            return ticker in self._prices
```

### The rounding contract

The cache rounds to 2 decimals **on write**, at the boundary, rather than in each data source or at each read. This is the reason a trade fills at exactly the price the user watched stream past: the SSE payload and the trade's fill price are the same `float`, from the same `PriceUpdate`, with no second rounding step to disagree about.

Rounding in the sources instead would work today but silently breaks the moment a third source is added that forgets to do it.

### `get_all()` returns a shallow copy on purpose

The copy is of the dict, not the `PriceUpdate` objects — and that is safe precisely because `PriceUpdate` is frozen. The caller gets a stable snapshot it can iterate without holding the lock, while the values inside it can never mutate underneath. This is what keeps the SSE critical section down to a ~10-entry dict copy.

### On the `version` counter

`version` is a monotonic write counter, held under the lock. It is **not** the SSE emit gate — the stream emits unconditionally ([§10.1](#101-why-the-stream-emits-unconditionally)). It survives because it is genuinely useful for diagnostics and for tests that need to assert "a write happened" without racing on wall-clock time.

The lock on a single `int` read is redundant under CPython's GIL. It is there anyway: it costs one uncontended acquisition twice a second, it is consistent with every other method on the class, and it is correct on free-threaded builds (PEP 703) where the GIL guarantee does not hold.

### Memory

O(number of priced tickers) — one `PriceUpdate` each, replaced on write. There is no history in the cache. The price series the UI draws is accumulated client-side from SSE (PLAN §10), and portfolio history lives in the `portfolio_snapshots` table.

---

## 5. Unified Interface — `interface.py`

The ABC every data source implements, plus the two error types that make failure legible to a route handler.

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
    schedule. Downstream code never calls the data source directly for prices —
    it reads from the cache.

    Lifecycle:
        source = create_market_data_source(cache)
        await source.start(["AAPL", "GOOGL", ...])
        # ... app runs ...
        await source.add_ticker("TSLA")
        price = await source.ensure_priced("PYPL")   # blocking, for trades
        await source.remove_ticker("GOOGL")
        # ... app shutting down ...
        await source.stop()
    """

    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Begin producing price updates for the given tickers.

        Starts a background task that periodically writes to the PriceCache.
        Must be called exactly once. Calling start() twice is undefined behavior.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Stop the background task and release resources.

        Safe to call multiple times. After stop(), the source will not write
        to the cache again.
        """

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Add a ticker to the active set. No-op if already present.

        Fire-and-forget: does NOT guarantee a price exists on return.
        Use ensure_priced() when a price is required immediately.
        """

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker from the active set. No-op if not present.

        Also removes the ticker from the PriceCache.
        """

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

### Contract table

| Method | Blocking? | Guarantees on return | Failure mode |
|---|---|---|---|
| `start(tickers)` | yes | Background task running; cache warm for the given tickers | Never called twice; behaviour undefined if it is |
| `stop()` | yes | Background task cancelled, resources released | Idempotent — safe after a failed `start` |
| `add_ticker(t)` | no (fire-and-forget) | Ticker is in the active set; **a price may not exist yet** | Silent no-op if already present |
| `remove_ticker(t)` | yes | Ticker gone from the active set *and* the cache | Silent no-op if absent |
| `get_tickers()` | n/a (sync) | Current active set as a new list | — |
| `ensure_priced(t, timeout)` | yes | A price is in the cache and returned; ticker joined the active set | Raises typed error; **no residue on failure** |

### Why `ensure_priced` exists, given `add_ticker`

`add_ticker` is deliberately fire-and-forget. The watchlist UI does not need to block: in Massive mode a newly added ticker simply shows up on the next poll, and a spinner for 15 seconds would be worse UX than a row that fills in a moment later.

Trades cannot work that way. PLAN §8 requires a trade in an unpriced ticker to auto-add it and fill **at execution time**. With only `add_ticker`, the trade route would face a cache miss and have to either reject (bad UX for a valid symbol), busy-wait up to 15 seconds (bad UX, and unbounded for a bad symbol), or invent a price (unacceptable).

`ensure_priced` is the synchronous, fallible counterpart: it either returns a price you can fill against, or raises a typed error the route maps directly to a status code. The two methods are not redundant — they answer different questions, and the split is what lets the watchlist stay snappy while trades stay correct.

### The no-residue guarantee

This is the property that makes rollback unnecessary at the route layer. A source must not leave a ticker in its active set, in the cache, or in the watchlist if `ensure_priced` raised.

Both implementations achieve it **by ordering rather than by compensation**: the symbol joins the active set only after a price has been confirmed and written. There is no `try/except` that undoes a partial write, because there is never a partial write to undo. Compensating rollback would have been the obvious approach and is strictly worse — it has its own failure mode (what if the rollback fails?), and it grows a new branch every time the method grows a new early return.

The route-level consequence is spelled out in [§12.3](#123-trade-execution).

### Error taxonomy & HTTP mapping

Three error types cover every rejection path. Routes map them to status codes without inspecting messages.

| Error | Defined in | Meaning | HTTP | Retry? |
|---|---|---|---|---|
| `InvalidSymbolFormatError` | `symbols.py` | The string cannot be a ticker at all (`NOT_A_STOCK`, `""`, `AA PL`) | 400 | No |
| `UnknownSymbolError` | `interface.py` | Well-formed, but this source cannot price it | 400 | No |
| `PricingUnavailableError` | `interface.py` | Valid symbol, no price obtainable right now (timeout, rate limit, network, source not running) | 503 | Yes |

The 400/503 split is the one distinction that matters to a caller: 400 means *this will never work, stop asking*; 503 means *try again in a moment*. That is exactly the information the chat flow needs to decide whether to tell the user "there's no such ticker" or "the market feed is briefly unavailable" — see [§12.4](#124-llm-issued-trades).

`InvalidSymbolFormatError` is raised by `normalize_symbol`, which runs *before* either the data source or the watchlist table is mutated. The two source-level errors are raised from `ensure_priced`.

---

## 6. Symbol Validation — `symbols.py`

PLAN §8 promises that an unrecognized symbol is rejected. Without this module the simulator would happily assign `NOT_A_STOCK` a random price between $50 and $300 and let the user trade it — a demo showing a plausible, moving price for a company that does not exist.

Validation happens in two layers, and both run *before* either the data source or the watchlist table is mutated:

1. **Shape validation (both modes)** — 1-5 uppercase letters, optionally `.` plus one or two letters for share classes (`BRK.B`). Cheap, and catches typos and injection-ish input before it reaches an API call or a SQL parameter.
2. **Existence validation (mode-specific)** — the simulator checks a curated universe; Massive asks the API. Both reject `NOT_A_STOCK`.

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
```

### The `(raw or "")` guard

`normalize_symbol(None)` raises `InvalidSymbolFormatError`, not `AttributeError`. Callers get one exception type for every bad input, including the `None` that arrives when an LLM emits `{"ticker": null}` in its structured output. Without the guard that path produces a 500 instead of a 400.

### The deliberate asymmetry between modes

The simulator is **stricter** than Massive about genuinely obscure real symbols. A small-cap that Massive prices happily will be rejected in simulator mode because it is not in `SIMULATED_UNIVERSE`.

This is the right bias, and it is worth being explicit about the trade-off rather than pretending it does not exist. The failure mode of being too strict is "the demo tells you it can't trade an obscure ticker" — mildly annoying, obviously correct behaviour. The failure mode of being too loose is "the demo shows a confident $184.22 price, a chart, and a P&L for a company that does not exist" — which undermines every number on the screen. Since the simulator is the *default* path that every student sees, it takes the conservative side.

Extending the universe is a one-line edit. Symbols in it but absent from `SEED_PRICES` get a random seed price and `DEFAULT_PARAMS`, which is fine — they are real companies, just not ones with hand-tuned volatility.

---

## 7. Market Simulator — `simulator.py`

The default source, used whenever `MASSIVE_API_KEY` is absent or empty. Runs entirely in-process with no external dependencies beyond NumPy. Two classes: `GBMSimulator` is the pure math engine, `SimulatorDataSource` is the `MarketDataSource` implementation that wraps it in an async loop.

### 7.1 The GBM math

Each tick advances every price by one step of Geometric Brownian Motion:

```
S(t+dt) = S(t) · exp( (mu − sigma²/2)·dt  +  sigma·√dt·Z )
```

- `mu` — annualized drift; `sigma` — annualized volatility; `Z` — a correlated standard normal draw.
- `dt` is 500 ms as a fraction of a *trading* year: `252 days × 6.5 h × 3600 s = 5,896,800 s`, so `dt = 0.5 / 5,896,800 ≈ 8.48e-8`.
- The `−sigma²/2` term is the Itô correction. Without it the simulated mean return exceeds `mu`, because `E[exp(X)] > exp(E[X])` for a normal `X` — prices would drift upward faster than the drift parameter claims.
- Because the update is multiplicative through `exp()`, prices are always positive. No clamping, no floor, no special-casing near zero.

Sub-cent per-tick moves accumulate into realistic-looking intraday paths over a few minutes of watching, which is exactly the timescale of a demo.

### 7.2 Correlated moves

Independent random walks look wrong: real tech names move together, and a terminal where AAPL rips while MSFT sags at the same instant reads as noise rather than as a market. Draw `n` independent normals and multiply by the Cholesky factor `L` of the correlation matrix `C` (where `C = L·Lᵀ`), giving draws with exactly the target correlation structure:

```
Z_correlated = L @ Z_independent
```

The matrix is rebuilt on every add/remove: O(n²) construction plus O(n³) decomposition. With n < 50 and changes only on watchlist edits, that is irrelevant next to the 500 ms tick budget — a 50×50 Cholesky is microseconds.

Correlation is assigned by sector membership: tech 0.6, finance 0.5, TSLA 0.3 (it sits in the tech set but is checked first so it behaves independently), everything else 0.3.

### 7.3 Random events

Roughly 0.1% chance per ticker per tick of a sudden 2-5% move in either direction. With 10 tickers at 2 ticks/sec, expect a visible shock roughly every 50 seconds — often enough to catch the eye during a demo, rare enough that it reads as an event rather than as noise.

### 7.4 Seed prices & parameters — `seed_prices.py`

Pure constants, no logic, no imports.

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

The volatility spread is what makes the terminal look alive. TSLA at `sigma=0.50` visibly jitters while V at `0.17` barely moves — the real-world contrast a user expects to see, and the cheapest possible way to make simulated data feel non-synthetic.

### 7.5 `GBMSimulator` — the math engine

```python
class GBMSimulator:
    """Geometric Brownian Motion simulator for correlated stock prices.

    Math:
        S(t+dt) = S(t) * exp((mu - sigma^2/2) * dt + sigma * sqrt(dt) * Z)
    """

    # 252 trading days * 6.5 hours/day * 3600 seconds/hour = 5,896,800 seconds
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
        """Advance all tickers by one time step. Returns {ticker: new_price}.

        This is the hot path — called every 500ms. Keep it fast.
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
            mu = params["mu"]
            sigma = params["sigma"]

            drift = (mu - 0.5 * sigma**2) * self._dt
            diffusion = sigma * math.sqrt(self._dt) * z_correlated[i]
            self._prices[ticker] *= math.exp(drift + diffusion)

            # Random event: ~0.1% chance per tick per ticker
            if random.random() < self._event_prob:
                shock_magnitude = random.uniform(0.02, 0.05)
                shock_sign = random.choice([-1, 1])
                self._prices[ticker] *= 1 + shock_magnitude * shock_sign
                logger.debug(
                    "Random event on %s: %.1f%% %s",
                    ticker, shock_magnitude * 100, "up" if shock_sign > 0 else "down",
                )

            result[ticker] = round(self._prices[ticker], 2)

        return result

    def add_ticker(self, ticker: str) -> None:
        """Add a ticker to the simulation. Rebuilds the correlation matrix."""
        if ticker in self._prices:
            return
        self._add_ticker_internal(ticker)
        self._rebuild_cholesky()

    def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker from the simulation. Rebuilds the correlation matrix."""
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
        """Add a ticker without rebuilding Cholesky (for batch initialization)."""
        if ticker in self._prices:
            return
        self._tickers.append(ticker)
        self._prices[ticker] = SEED_PRICES.get(ticker, random.uniform(50.0, 300.0))
        self._params[ticker] = TICKER_PARAMS.get(ticker, dict(DEFAULT_PARAMS))

    def _rebuild_cholesky(self) -> None:
        """Rebuild the Cholesky decomposition of the ticker correlation matrix."""
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

        try:
            self._cholesky = np.linalg.cholesky(corr)
        except np.linalg.LinAlgError:
            logger.warning(
                "Correlation matrix not positive semi-definite; using independent draws"
            )
            self._cholesky = None

    @staticmethod
    def _pairwise_correlation(t1: str, t2: str) -> float:
        """Sector-based correlation: tech 0.6, finance 0.5, TSLA 0.3, cross 0.3."""
        tech = CORRELATION_GROUPS["tech"]
        finance = CORRELATION_GROUPS["finance"]

        # TSLA is in the tech set but behaves independently — checked first
        if t1 == "TSLA" or t2 == "TSLA":
            return TSLA_CORR

        if t1 in tech and t2 in tech:
            return INTRA_TECH_CORR
        if t1 in finance and t2 in finance:
            return INTRA_FINANCE_CORR

        return CROSS_GROUP_CORR
```

Three details worth noting:

- **`_add_ticker_internal` vs `add_ticker`.** The internal variant skips the Cholesky rebuild so that constructing a 10-ticker simulator does one decomposition instead of ten. `add_ticker` is the public single-item path and does rebuild.
- **`dict(DEFAULT_PARAMS)` is copied, not shared.** Handing every unknown ticker the same dict object means a future per-ticker parameter tweak would silently mutate every other unknown ticker. The copy costs nothing and removes the footgun.
- **`_pairwise_correlation` checks TSLA first.** TSLA is a member of `CORRELATION_GROUPS["tech"]`, so if the tech check ran first TSLA would correlate at 0.6 with the rest of tech and the `TSLA_CORR` constant would be dead code. Order is load-bearing here.

### 7.6 Non-PSD correlation matrix

`np.linalg.cholesky` raises `LinAlgError` on a matrix that is not positive semi-definite. The current three-tier structure (0.6 / 0.5 / 0.3) is PSD for any ticker mix, but anyone widening the spread — say tech to 0.9 while cross stays 0.1 — can break it. Because `_rebuild_cholesky` is called from `add_ticker`, which is called from a request handler, an unhandled `LinAlgError` would surface as a 500 on "add ticker to watchlist".

The fallback above degrades to independent draws and logs a warning. Losing correlation makes the simulation slightly less realistic; failing the request makes the app look broken. The trade is obvious in that direction.

### 7.7 `SimulatorDataSource` — lifecycle

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
        # Seed the cache with initial prices so SSE has data immediately
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
        symbol = normalize_symbol(ticker)
        if self._sim:
            self._sim.add_ticker(symbol)
            # Seed cache immediately so the ticker has a price right away
            price = self._sim.get_price(symbol)
            if price is not None:
                self._cache.update(ticker=symbol, price=price)
            logger.info("Simulator: added ticker %s", symbol)

    async def remove_ticker(self, ticker: str) -> None:
        symbol = normalize_symbol(ticker)
        if self._sim:
            self._sim.remove_ticker(symbol)
        self._cache.remove(symbol)
        logger.info("Simulator: removed ticker %s", symbol)

    def get_tickers(self) -> list[str]:
        return self._sim.get_tickers() if self._sim else []

    async def ensure_priced(self, ticker: str, timeout: float = 5.0) -> float:
        """Validate against the simulated universe, then seed a price synchronously.

        The simulator is authoritative and instantaneous: if the symbol is in the
        universe we can always produce a price, so `timeout` is unused here.
        """
        symbol = normalize_symbol(ticker)  # raises InvalidSymbolFormatError
        if not is_simulated(symbol):
            raise UnknownSymbolError(
                f"{symbol} is not a symbol this simulated market trades"
            )
        cached = self._cache.get_price(symbol)
        if cached is not None:
            return cached
        await self.add_ticker(symbol)  # seeds the cache synchronously
        price = self._cache.get_price(symbol)
        if price is None:  # only if start() was never called
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

**Immediate seeding.** `start()` populates the cache *before* creating the loop task, so `start()` returning means the cache is warm. The first SSE event a browser receives carries real prices instead of an empty object, and there is no blank-grid flash on page load.

**The bare `except Exception` in `_run_loop` is deliberate** and is invariant 4 from [§1](#1-architecture). A background task that dies takes the whole market with it, and the symptom the user sees is prices silently freezing — no error, no indicator, just a terminal that stopped being alive. Log the exception and keep ticking; a single bad tick is recoverable, a dead loop is not. Note the `except` sits *inside* the `while`, so the `await asyncio.sleep()` still runs on the failure path and a persistent exception cannot spin the event loop.

**`ensure_priced` never awaits I/O here.** The simulator is authoritative and synchronous — if the symbol is in the universe, a price can always be produced right now. The `timeout` parameter exists only to satisfy the interface, and that asymmetry with the Massive implementation is fine: the contract promises *at most* `timeout`, not *exactly*.

---

## 8. Massive API Client — `massive_client.py`

The optional real-data source, used whenever `MASSIVE_API_KEY` is set and non-empty. Massive is the successor to Polygon.io; the Python package is `massive` (`uv add massive`), base URL `https://api.massive.com`, auth via `Authorization: Bearer <key>` which `RESTClient` handles.

### 8.1 Why REST polling, not WebSocket

Polling is deliberate. WebSocket streaming is available on paid tiers only, adds a reconnect/backoff state machine, and would deliver updates on a cadence the SSE layer would then have to reconcile against. Polling works on every account tier including free, and — critically — **one batch call covers the entire watchlist**:

`get_snapshot_all(market_type=STOCKS, tickers=[...])` returns every requested ticker in a *single* request. Ticker count therefore never affects rate-limit headroom; only poll frequency does. A second endpoint, `get_snapshot_ticker(...)`, fetches one symbol on demand and is used only by `ensure_priced`.

### 8.2 Response shape

The fields that matter, per snapshot:

```json
{
  "ticker": "AAPL",
  "day":        { "previous_close": 129.61, "change_percent": -3.50, "volume": 111237700 },
  "last_trade": { "price": 125.07, "size": 100, "timestamp": 1675190399000 }
}
```

We read `last_trade.price` and `last_trade.timestamp`. **Timestamps are Unix milliseconds and must be divided by 1000** — the cache and `PriceUpdate` are in seconds throughout, and a millisecond timestamp leaking into the cache would put that ticker's point 50,000 years into the future on the frontend's time axis.

`day.previous_close` is not used today; see the note on day-over-day change in [§3](#3-data-model--modelspy).

### 8.3 Implementation

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

_MAX_CONSECUTIVE_FAILURES_BEFORE_ESCALATION = 3


class MassiveDataSource(MarketDataSource):
    """MarketDataSource backed by the Massive (Polygon.io) REST API.

    Polls GET /v2/snapshot/locale/us/markets/stocks/tickers for all watched
    tickers in a single API call, then writes results to the PriceCache.

    Rate limits:
      - Free tier: 5 req/min → poll every 15s (default)
      - Paid tiers: higher limits → poll every 2-5s
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
        self._consecutive_failures: int = 0

    async def start(self, tickers: list[str]) -> None:
        self._client = RESTClient(api_key=self._api_key)
        self._tickers = list(tickers)

        # Do an immediate first poll so the cache has data right away
        await self._poll_once()

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
        except TimeoutError as exc:
            raise PricingUnavailableError(f"Timed out fetching a price for {symbol}") from exc
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
        """Poll on interval. First poll already happened in start()."""
        while True:
            await asyncio.sleep(self._interval)
            await self._poll_once()

    async def _poll_once(self) -> None:
        """Execute one poll cycle: fetch snapshots, update cache. Never raises."""
        if not self._tickers or not self._client:
            return

        try:
            # The Massive RESTClient is synchronous — run in a thread to
            # avoid blocking the event loop.
            snapshots = await asyncio.to_thread(self._fetch_snapshots)
            processed = 0
            for snap in snapshots:
                try:
                    price = snap.last_trade.price
                    # Massive timestamps are Unix milliseconds → convert to seconds
                    timestamp = snap.last_trade.timestamp / 1000.0
                    self._cache.update(ticker=snap.ticker, price=price, timestamp=timestamp)
                    processed += 1
                except (AttributeError, TypeError) as e:
                    logger.warning(
                        "Skipping snapshot for %s: %s", getattr(snap, "ticker", "???"), e
                    )
            logger.debug("Massive poll: updated %d/%d tickers", processed, len(self._tickers))
            self._consecutive_failures = 0

        except Exception as e:
            # Don't re-raise — the loop will retry on the next interval.
            # Common failures: 401 (bad key), 429 (rate limit), network errors.
            self._consecutive_failures += 1
            if self._consecutive_failures >= _MAX_CONSECUTIVE_FAILURES_BEFORE_ESCALATION:
                logger.error(
                    "Massive poll failed %d times in a row (possible bad API key "
                    "or persistent network issue): %s",
                    self._consecutive_failures, e,
                )
            else:
                logger.error("Massive poll failed: %s", e)

    def _fetch_snapshots(self) -> list:
        """Synchronous call to the Massive REST API. Runs in a thread."""
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

**`asyncio.to_thread` everywhere.** The `RESTClient` is synchronous, so every call is offloaded to a worker thread to keep the event loop free. That worker-thread write is precisely why `PriceCache` uses a `threading.Lock` rather than an asyncio primitive ([§4](#4-price-cache--cachepy)) — the two decisions are one decision.

**Imports are at module level, not lazy.** An earlier version lazy-imported `massive` inside `start()` so the package would be optional for simulator-only use. That bought nothing — `massive` is a declared core dependency in `pyproject.toml`, so it is always installed — and it actively broke `unittest.mock.patch("app.market.massive_client.RESTClient")`, because the name did not exist at module scope for the patcher to find.

**`except TimeoutError` before the general handler.** On Python 3.11+ `asyncio.TimeoutError` is an alias of the builtin `TimeoutError`, so this catches `wait_for` expiry. Order matters: it must precede `except Exception`, or a timeout would be classified by `_is_not_found` and could be reported as a permanent rejection of a perfectly valid symbol.

**`_is_not_found` fails toward "transient".** When it cannot classify an exception it returns `False`, which routes to `PricingUnavailableError` (503, retryable). That is the safe direction: telling a user "try again shortly" about a symbol that turns out to be bogus is a mild annoyance, whereas permanently rejecting `AAPL` because of a transient 502 is a bug the user cannot work around.

### 8.4 Ticker management

| Operation | Behaviour | Latency to a price |
|---|---|---|
| `start(tickers)` | Sets the polled list, performs an immediate first poll, then starts the loop | one round trip |
| `add_ticker(t)` | Normalizes and appends to the polled list. Fire-and-forget — **no price on return** | up to `poll_interval` |
| `remove_ticker(t)` | Normalizes, drops from the polled list, evicts from the cache | n/a |
| `ensure_priced(t)` | Fetches that one symbol immediately with a timeout; joins the polled list only on success | one round trip, bounded by `timeout` |

Note the cache-hit fast path in `ensure_priced` checks **both** that a price is cached and that the symbol is in `self._tickers`. A cached price for a symbol that is not being polled is stale by construction — it will never be refreshed — so the method re-fetches rather than filling a trade against a price frozen at whatever moment the symbol left the polled set.

### 8.5 Poll interval & rate limits

| Tier | Limit | `poll_interval` | Calls/min |
|---|---|---|---|
| Free | 5 req/min | `15.0` (default) | 4 |
| Starter / paid | effectively unlimited | `5.0` | 12 |
| Advanced | unlimited | `2.0` | 30 |

The free-tier default of 15 s uses 4 of 5 calls per minute, leaving exactly one call of headroom — which is what `ensure_priced` spends when a user trades an unwatched ticker. That is not a coincidence; it is why the default is 15 and not 12.

Because the batch endpoint collapses all tickers into one request, ticker count cannot trip the rate limit. Only a too-short `MASSIVE_POLL_INTERVAL` can.

### 8.6 Market-hours behaviour

Outside regular trading hours `last_trade.price` is the last print (possibly after-hours), so prices simply stop moving. This is correct and needs no special handling — but it is exactly why the SSE contract must keep emitting `"flat"` ticks rather than falling silent ([§10.1](#101-why-the-stream-emits-unconditionally)). A user opening the app at 9pm should see a still market with a green connection dot, not a blank grid that looks broken.

### 8.7 No runtime failover to the simulator

The source is chosen once, at startup, by `create_market_data_source()`. There is no automatic fallback to the simulator when the API fails.

This is the single most tempting piece of "robustness" to add and it would be a mistake. Falling back mid-session would silently mix invented prices into a real-data feed, with no marker in the payload saying which is which — the user's positions would be valued against fiction while the UI claims live data. Stale real prices are honest; fresh fake ones are not. To fall back, unset `MASSIVE_API_KEY` and restart.

---

## 9. Factory — `factory.py`

One environment variable decides everything.

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
    """Create the appropriate market data source based on environment variables.

    - MASSIVE_API_KEY set and non-empty → MassiveDataSource (real market data)
    - Otherwise → SimulatorDataSource (GBM simulation)

    Returns an unstarted source. Caller must await source.start(tickers).
    """
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()

    if api_key:
        poll_interval = float(os.environ.get("MASSIVE_POLL_INTERVAL", "15.0"))
        logger.info("Market data source: Massive API (poll every %.1fs)", poll_interval)
        return MassiveDataSource(
            api_key=api_key, price_cache=price_cache, poll_interval=poll_interval
        )
    else:
        logger.info("Market data source: GBM Simulator")
        return SimulatorDataSource(price_cache=price_cache)
```

`.strip()` on the key matters: `MASSIVE_API_KEY=` and `MASSIVE_API_KEY="   "` in a `.env` file both mean "not configured", and without the strip the second would select the Massive client and then fail every poll with a 401.

The factory returns an **unstarted** source. Construction is pure — no I/O, no tasks, no network — so it is safe to call at import time or in a test; only `start()` has effects. That separation is what makes `test_factory.py` able to assert selection logic without any mocking of the network.

`MASSIVE_POLL_INTERVAL` lets a paid-tier user drop to 2-5 s without a code change. Absent, it defaults to the free-tier-safe 15 s.

---

## 10. SSE Streaming — `stream.py`

The endpoint is `GET /api/stream/prices`, a long-lived `text/event-stream` connection the browser opens with the native `EventSource` API.

### 10.1 Why the stream emits unconditionally

PLAN §6 requires: *"The stream re-emits every priced ticker each tick, including unchanged ones (`flat`)."* This is the contract, and it exists for a reason worth stating plainly.

The obvious implementation is to gate emission on `PriceCache.version` and skip the send when nothing changed. In simulator mode that is invisible — the cache changes every 500 ms, so it emits every 500 ms either way. **In Massive mode it means the stream goes silent for up to 15 seconds at a time**, and silence on an SSE connection is indistinguishable from a dead connection. The frontend cannot tell a quiet market from a crashed backend, and the connection-status dot becomes a lie.

There is a second, subtler problem underneath. `PriceUpdate.direction` is relative to the last *cache write* ([§3](#3-data-model--modelspy)). Naively re-emitting the cached update between polls would repeat `"up"` on every tick, and the frontend — which flashes a row green on any non-flat direction — would strobe that row twice a second for fifteen seconds on the strength of one real uptick.

So the resolution has two halves, and both are necessary:

1. **Emit every interval, unconditionally.** Unchanged tickers report `"flat"`. Silence now means a real connection problem, and the 500 ms cadence doubles as the keepalive — no separate heartbeat comment is needed.
2. **Compute `direction` per connection.** Each connection remembers the last price *it* sent for each ticker and derives `change`/`direction` against that. This makes `direction` answer exactly the question the frontend asks — "did this change since the event I last received?" — so a ticker that did not move reports `"flat"` with `change: 0.0` and triggers no animation.

### 10.2 Payload

```
retry: 1000

data: {"seq":41,"ts":1738012800.5,"prices":{
  "AAPL":{"ticker":"AAPL","price":190.52,"previous_price":190.48,"change":0.04,
          "change_percent":0.021,"direction":"up","timestamp":1738012800.4},
  "JPM": {"ticker":"JPM","price":195.10,"previous_price":195.10,"change":0.0,
          "change_percent":0.0,"direction":"flat","timestamp":1738012788.1}}}
```

- **The `{seq, ts, prices}` envelope is extensible; a bare ticker-keyed map is not.** With prices at the top level, any future top-level key (`"status"`, `"mode"`) could collide with a real ticker symbol. Nesting them under `prices` makes that impossible.
- **`seq` increments per connection**, so a client can detect gaps, and dev-tools show liveness at a glance.
- **`previous_price` is the last price this connection was sent**, which is what makes `change` and `direction` internally consistent for animation.
- **Default event type** (no `event:` line), so the frontend uses plain `EventSource.onmessage`.

### 10.3 Implementation

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

    A fresh APIRouter per call so the route can't be registered twice when
    tests build more than one app.
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

Four details that are easy to get wrong:

- **`last_sent` is rebuilt from the snapshot, not updated in place.** A ticker removed from the watchlist drops out of `last_sent` automatically, so if it is later re-added the first event reports `"flat"` rather than diffing against a price from ten minutes ago.
- **A first-seen ticker reports `"flat"`.** `_diff` sets `previous = price` when `last is None`, so a newly added row does not flash on arrival.
- **The `if prices:` guard** means an empty watchlist produces no events rather than a stream of `{"prices": {}}`. The connection stays open and resumes the moment a ticker is added.
- **`raise` after logging `CancelledError`.** Swallowing it would break structured cancellation — the server could not shut the connection down cleanly during app teardown.

### 10.4 Client usage

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

There is no `Last-Event-ID` replay (PLAN §6). A reconnecting client resumes from the live cache and any ticks missed during the gap are gone. Sparklines therefore show a small gap after a reconnect, which is acceptable — the series is a session-lifetime visual, not a record. The P&L chart, which *is* a record, is backed by `portfolio_snapshots` and survives reload.

---

## 11. FastAPI Lifecycle Integration

The market data source starts in the app lifespan, **after** DB init (PLAN §7 requires the schema to exist before the market task runs) and before any request is served.

```python
"""app/main.py — market data wiring."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.db import get_open_position_tickers, get_watchlist_tickers, init_db
from app.market import (
    MarketDataSource,
    PriceCache,
    create_market_data_source,
    create_stream_router,
)

# Constructed at import time: PriceCache() does no I/O, so this is safe, and it
# lets the SSE router be registered against the same instance the lifespan starts.
price_cache = PriceCache()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Schema + seed data must exist before anything reads the DB
    init_db()

    # 2. Priced set = watchlist ∪ open positions (PLAN §6)
    tickers = sorted(set(get_watchlist_tickers()) | set(get_open_position_tickers()))

    # 3. Start the market data source — cache is warm when start() returns
    source = create_market_data_source(price_cache)
    await source.start(tickers)

    # 4. Publish on app.state for route dependencies
    app.state.price_cache = price_cache
    app.state.market_source = source

    try:
        yield
    finally:
        await source.stop()


app = FastAPI(title="FinAlly", lifespan=lifespan)
app.include_router(create_stream_router(price_cache))


# --- Dependencies for other routers ---

def get_price_cache(request: Request) -> PriceCache:
    return request.app.state.price_cache


def get_market_source(request: Request) -> MarketDataSource:
    return request.app.state.market_source
```

**Why `price_cache` is module-scoped.** `create_stream_router` needs the cache at router-registration time, which happens at import, whereas `lifespan` runs later. Constructing the cache at module scope resolves the ordering with no ceremony — `PriceCache()` is pure. The alternative, registering the router inside `lifespan` before `yield`, also works but scatters route registration across two places.

**`try/finally` around the `yield`.** `source.stop()` must run even if the app raises during shutdown, or the background task leaks and the process may not exit.

**Startup order is load-bearing.** `init_db()` must precede the ticker query (nothing to read from otherwise), and both must precede `source.start()` (which needs the ticker list). This is the whole of PLAN §7's requirement that DB init happen in a startup event rather than lazily on first request.

---

## 12. Watchlist & Trade Coordination

### 12.1 Add to watchlist

Validate and price **first**, write the DB row only on success — so a rejected symbol never leaves a row behind.

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

`ensure_priced` rather than `add_ticker` here, even though the watchlist does not strictly need a price on return: it is the only way to reject a bad symbol at the moment the user types it, rather than showing a row that never populates.

### 12.2 Remove from watchlist

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

Skipping this check is the bug that makes a user's portfolio show a held position with no price the moment they tidy their watchlist.

### 12.3 Trade execution

The fill price comes from the cache; an unpriced ticker is auto-added; an unrecognized symbol is rejected — and each of those has exactly one meaning in both modes.

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

**Rollback semantics.** There is nothing to roll back. `ensure_priced` joins the ticker to the polled set only after a price is confirmed, and the watchlist row is written only after the trade succeeds. A failed lookup or a failed validation leaves the watchlist, the polled set, and the cache exactly as they were. This is the route-level payoff of the no-residue guarantee in [§5](#5-unified-interface--interfacepy).

**Timeout budget.** 5 s is one Massive round trip with slack, well under a browser's patience and well under any sensible gateway timeout. In simulator mode `ensure_priced` returns without awaiting I/O at all.

**The price is never sent by the client.** It is read from the cache at execution time. A client-supplied price would be trivially spoofable, and — more mundanely — would disagree with the streamed price whenever the user's tab was stale.

### 12.4 LLM-issued trades

PLAN §9 requires LLM trades to go through identical validation. Call the same service function the route calls — **not** the HTTP route — and translate raised errors into the `actions.errors` array of the chat response:

```python
for t in llm_response.trades:
    try:
        executed.append(await trade_service.execute(t.ticker, t.side, t.quantity))
    except (UnknownSymbolError, InvalidSymbolFormatError, ValidationError) as e:
        errors.append(str(e))
    except PricingUnavailableError as e:
        errors.append(f"{t.ticker}: {e}")
```

Sharing the service function rather than the route is what guarantees "identical validation" stays true as the rules evolve — there is one implementation, so the two paths cannot drift. Going through HTTP would also mean parsing status codes back out of a response the process just generated for itself.

This is also where the error taxonomy earns its keep: `UnknownSymbolError` produces "there is no such ticker", `PricingUnavailableError` produces "the feed is briefly unavailable, try again", and the LLM can relay either one accurately to the user.

---

## 13. Error Handling & Edge Cases

**13.1 Empty watchlist at startup.** `start([])` is valid. The simulator's `step()` returns `{}`; the Massive poller skips its API call entirely (`if not self._tickers`). The SSE loop yields nothing until a ticker exists, then resumes. Adding a ticker recovers immediately with no restart.

**13.2 Cache miss on a held position.** Should not happen — startup unions positions into the priced set ([§11](#11-fastapi-lifecycle-integration)). If it does (e.g. a Massive symbol that stopped returning trades), portfolio valuation must treat the position as `None`-priced and **exclude it from `total_value`**, rather than valuing it at zero. Valuing at zero displays a fake catastrophic loss and would poison `portfolio_snapshots` with a bogus data point that survives restart.

**13.3 Invalid Massive API key.** The first poll fails with 401, is logged, and the loop keeps retrying. The cache stays empty, so SSE emits nothing and the UI shows a connected-but-empty terminal — the single most confusing failure mode this app has, because every indicator says "fine". Hence the escalation counter in `_poll_once`: after 3 consecutive failures the log line is promoted to `ERROR` and names a bad API key explicitly. Surfacing this through `/api/health` is a reasonable follow-on.

**13.4 Rate limiting (429).** Caught by the same handler and retried on the next interval. Ticker count cannot cause this ([§8.5](#85-poll-interval--rate-limits)); only a too-short `MASSIVE_POLL_INTERVAL` can.

**13.5 Malformed snapshot.** A snapshot missing `last_trade` raises `AttributeError`/`TypeError`, is logged per ticker, and is skipped. Other tickers in the same batch still update — the per-snapshot `try` is inside the loop precisely so one bad symbol cannot cost the other nine their update.

**13.6 Trade against a stale price.** In Massive mode the cached price can be up to `poll_interval` old. Accepted: no fees, no slippage, fake money. Worth stating in the UI as "prices delayed up to 15 s" when a key is configured.

**13.7 Lock contention.** At 10 tickers × 2 Hz, plus one `get_all()` per SSE client per tick, the critical section is a dict copy of ~10 entries. Negligible. A read-write lock would be the fix if this ever mattered; at this scale it never will.

**13.8 Clock source for `timestamp`.** Simulator timestamps come from `time.time()` (wall clock); Massive timestamps come from the exchange. Both are Unix seconds, so the frontend can plot them on one axis — but Massive timestamps can appear slightly stale relative to local time. Do not compute "data age" by subtracting them from `Date.now()` and alarming the user.

**13.9 Floating-point precision.** Not a concern. The exponential formulation is numerically stable, prices are rounded to 2 decimals at the cache boundary, and GBM cannot produce a non-positive price.

---

## 14. Configuration

The deployment-facing surface is two environment variables:

| Variable | Default | Description |
|---|---|---|
| `MASSIVE_API_KEY` | `""` | Non-empty → Massive API; otherwise the GBM simulator |
| `MASSIVE_POLL_INTERVAL` | `15.0` s | Massive poll cadence. Free tier: leave at 15. Paid: 2-5 |

Per-component tuning parameters are in code, not the environment — they are development knobs, not deployment ones:

| Parameter | Location | Default | Description |
|---|---|---|---|
| `update_interval` | `SimulatorDataSource.__init__` | `0.5` s | Simulator tick cadence |
| `event_probability` | `GBMSimulator.__init__` | `0.001` | Shock chance per ticker per tick |
| `dt` | `GBMSimulator.__init__` | `~8.48e-8` | GBM step (fraction of a trading year) |
| `poll_interval` | `MassiveDataSource.__init__` | `15.0` s | Poll cadence; set from `MASSIVE_POLL_INTERVAL` |
| `timeout` | `ensure_priced` | `5.0` s | On-demand price fetch budget |
| `interval` | `create_stream_router` | `0.5` s | SSE emit cadence |
| retry directive | `_generate_events` | `1000` ms | EventSource reconnect delay |

---

## 15. Testing

**127 tests, all passing. 97% statement coverage of `app/market/`.**

```bash
cd backend
uv sync --extra dev
uv run --extra dev pytest -v              # All tests
uv run --extra dev pytest --cov=app       # With coverage
uv run --extra dev ruff check app/ tests/ # Lint
```

| Test module | Tests | Covers |
|---|---|---|
| `test_models.py` | 11 | `PriceUpdate` construction, derived properties, `to_dict`, zero-division guard |
| `test_cache.py` | 15 | update/get/remove, direction transitions, version counter, thread safety |
| `test_symbols.py` | 22 | `normalize_symbol` accept/reject, `None` handling, universe membership |
| `test_simulator.py` | 19 | GBM math, positivity, add/remove, Cholesky rebuild, full 10-ticker matrix |
| `test_simulator_source.py` | 15 | Lifecycle, immediate seeding, `ensure_priced`, no-residue on rejection |
| `test_massive.py` | 21 | Poll parsing, ms→s conversion, malformed snapshots, error classification, no-residue |
| `test_stream.py` | 14 | SSE contract: unconditional emit, per-connection direction, envelope shape |
| `test_factory.py` | 10 | Source selection, `MASSIVE_POLL_INTERVAL` parsing, whitespace-only key |

| Module | Coverage |
|---|---|
| `cache.py`, `models.py`, `symbols.py`, `factory.py`, `interface.py`, `seed_prices.py`, `__init__.py` | 100% |
| `stream.py` | 98% |
| `simulator.py` | 96% |
| `massive_client.py` | 94% |

### 15.1 The tests that matter most

Three behaviours are worth writing down because they are the ones a refactor is most likely to break silently.

**The stream must keep emitting when the cache is static** — the Massive-mode case, and the reason for [§10.1](#101-why-the-stream-emits-unconditionally):

```python
@pytest.mark.asyncio
async def test_stream_emits_flat_when_cache_is_static():
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
```

**`ensure_priced` must leave no residue when it fails** — asserted against both sources, because the guarantee is a property of the *interface*, not of either implementation:

```python
@pytest.mark.asyncio
async def test_simulator_ensure_priced_rejects_unknown():
    cache = PriceCache()
    source = SimulatorDataSource(price_cache=cache)
    await source.start(["AAPL"])

    with pytest.raises(UnknownSymbolError):
        await source.ensure_priced("ZZZZ")      # valid shape, not a real company
    assert "ZZZZ" not in source.get_tickers()   # no residue
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

    assert source.get_tickers() == []           # rollback-free by construction
```

**The cache must survive concurrent writers**, since the Massive client writes from a worker thread while SSE reads on the loop:

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

### 15.2 Mocking the Massive client

`massive` is a core dependency and is imported at module level, so patch targets resolve normally. Tests set `source._client` to a `MagicMock()` and patch `_fetch_snapshots` / `_fetch_one` **by name on the instance** — not the `RESTClient` methods — which keeps the tests independent of the vendor SDK's internal call signatures.

```python
def _make_snapshot(ticker: str, price: float, timestamp_ms: int) -> MagicMock:
    snap = MagicMock()
    snap.ticker = ticker
    snap.last_trade.price = price
    snap.last_trade.timestamp = timestamp_ms
    return snap
```

Worth keeping covered alongside the no-residue test: a 404-shaped exception maps to `UnknownSymbolError`, a malformed snapshot in a batch does not stop sibling tickers updating, and a poll that raises does not kill `_poll_loop`.

### 15.3 E2E hooks (`test/`)

- Fresh start: 10 tickers appear with prices within 2 s.
- Prices visibly change over 5 s (simulator mode).
- SSE resilience: kill the connection, confirm `EventSource` reconnects and prices resume.
- Add `PYPL` via the trade bar with no prior watchlist entry → position appears, ticker joins the watchlist.
- Trade `NOT_A_STOCK` → 400 with a readable message, **no watchlist row created**.

### 15.4 Demo

A Rich terminal dashboard exercises the simulator end to end without the frontend:

```bash
cd backend
uv run market_data_demo.py
```

Live-updating table of all 10 default tickers with sparklines, color-coded direction arrows, and an event log for notable moves. Runs 60 seconds or until Ctrl+C. Useful as a smoke test that the simulator, cache, and source lifecycle all work before any HTTP is involved.
