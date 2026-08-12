# Market Simulator — GBM Design

The default market data source: a Geometric Brownian Motion simulator with sector-correlated moves, running entirely in-process with no external dependencies. Used whenever `MASSIVE_API_KEY` is absent or empty.

Also covers `symbols.py`, the source-independent symbol validation layer, because the simulator is where the curated tradeable universe is defined.

The contracts this source implements are in [`market_interface.md`](market_interface.md); the real-data alternative is in [`massive_api.md`](massive_api.md).

Snippets are labelled **as built** or **change required**.

---

## Table of Contents

1. [The GBM Math](#1-the-gbm-math)
2. [Correlated Moves](#2-correlated-moves)
3. [Random Events](#3-random-events)
4. [Seed Prices & Parameters — `seed_prices.py`](#4-seed-prices--parameters--seed_pricespy)
5. [Symbol Validation — `symbols.py`](#5-symbol-validation--symbolspy)
6. [`GBMSimulator` — `simulator.py`](#6-gbmsimulator--simulatorpy)
7. [`SimulatorDataSource` — Lifecycle](#7-simulatordatasource--lifecycle)
8. [Non-PSD Correlation Matrix](#8-non-psd-correlation-matrix)
9. [Configuration](#9-configuration)
10. [Testing](#10-testing)

---

## 1. The GBM Math

Each tick advances every price by one step of Geometric Brownian Motion:

```
S(t+dt) = S(t) · exp( (mu − sigma²/2)·dt  +  sigma·√dt·Z )
```

- `mu` — annualized drift, `sigma` — annualized volatility, `Z` — correlated standard normal.
- `dt` is 500 ms as a fraction of a *trading* year: `252 days × 6.5 h × 3600 s = 5,896,800 s`, so `dt = 0.5 / 5,896,800 ≈ 8.48e-8`.
- The `−sigma²/2` term is the Itô correction; without it the simulated mean return exceeds `mu`.
- Because the update is multiplicative through `exp()`, prices are always positive — no clamping needed.

Sub-cent per-tick moves accumulate into realistic-looking intraday paths over a few minutes of watching.

---

## 2. Correlated Moves

Independent random walks look wrong — real tech names move together. We draw `n` independent normals and multiply by the Cholesky factor `L` of the correlation matrix `C` (`C = L·Lᵀ`), giving draws with exactly the target correlation structure:

```
Z_correlated = L @ Z_independent
```

The matrix is rebuilt on every add/remove. That's O(n²) construction plus O(n³) decomposition, but n < 50 and changes are rare (a watchlist edit), so it is irrelevant next to the 500 ms tick budget.

Correlation is assigned by sector membership: tech 0.6, finance 0.5, TSLA 0.3 (it sits in the tech set but behaves independently), everything else 0.3.

---

## 3. Random Events

Roughly 0.1% chance per ticker per tick of a sudden 2-5% move in either direction, for visual drama. With 10 tickers at 2 ticks/sec, expect a visible shock roughly every 50 seconds. Controlled by `event_probability`.

---

## 4. Seed Prices & Parameters — `seed_prices.py`

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

`normalize_symbol` is exported from `app.market` and used by the Massive client too; `InvalidSymbolFormatError` maps to HTTP 400 (see [`market_interface.md` §4](market_interface.md#4-error-taxonomy--http-mapping)).

---

## 6. `GBMSimulator` — `simulator.py`

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

---

## 7. `SimulatorDataSource` — Lifecycle

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

Because the simulator is authoritative and synchronous, `ensure_priced` never awaits I/O — the `timeout` parameter exists only to satisfy the interface.

---

## 8. Non-PSD Correlation Matrix

`np.linalg.cholesky` raises `LinAlgError` on a non-positive-semi-definite matrix. The current three-tier structure (0.6 / 0.5 / 0.3) is PSD for any ticker mix, but anyone widening the spread — say tech to 0.9 while cross stays 0.1 — can break it. Since `_rebuild_cholesky` is called from `add_ticker`, that error would propagate into a request.

**Change required:** fall back to uncorrelated draws rather than failing the request.

```python
# _rebuild_cholesky(), replacing the bare decomposition:
try:
    self._cholesky = np.linalg.cholesky(corr)
except np.linalg.LinAlgError:
    logger.warning("Correlation matrix not positive semi-definite; using independent draws")
    self._cholesky = None
```

---

## 9. Configuration

| Parameter | Location | Default | Description |
|---|---|---|---|
| `update_interval` | `SimulatorDataSource.__init__` | `0.5` s | Simulator tick cadence |
| `event_probability` | `GBMSimulator.__init__` | `0.001` | Shock chance per ticker per tick |
| `dt` | `GBMSimulator.__init__` | `~8.48e-8` | GBM step (fraction of a trading year) |

Selection is by absence of `MASSIVE_API_KEY` — see [`MARKET_DATA_DESIGN.md` §14](MARKET_DATA_DESIGN.md#14-configuration).

---

## 10. Testing

Existing simulator coverage: `test_simulator.py` (17 tests, 98%) and `test_simulator_source.py` (10 integration tests). The additions below cover the new behaviour in this document.

### 10.1 Symbol validation (new)

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

### 10.2 `ensure_priced` (new)

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
```

### 10.3 Full default watchlist Cholesky (new)

```python
def test_cholesky_succeeds_for_all_default_tickers():
    sim = GBMSimulator(tickers=list(SEED_PRICES))
    assert sim._cholesky is not None
    prices = sim.step()
    assert len(prices) == 10 and all(p > 0 for p in prices.values())
```
