# Massive API Integration

The optional real-market-data source: a REST polling client for Massive (the successor to Polygon.io), used whenever `MASSIVE_API_KEY` is set and non-empty. It implements the same `MarketDataSource` contract as the simulator, so nothing downstream of the `PriceCache` changes.

The contracts this source implements are in [`market_interface.md`](market_interface.md); the default source is in [`market_simulator.md`](market_simulator.md).

Snippets are labelled **as built** or **change required**.

---

## Table of Contents

1. [The API](#1-the-api)
2. [Response Shape](#2-response-shape)
3. [Implementation — `massive_client.py`](#3-implementation--massive_clientpy)
4. [Ticker Management](#4-ticker-management)
5. [Poll Interval & Rate Limits](#5-poll-interval--rate-limits)
6. [Error Handling & Fallback Behaviour](#6-error-handling--fallback-behaviour)
7. [Configuration](#7-configuration)
8. [Testing](#8-testing)

---

## 1. The API

- Package `massive` (`uv add massive`), successor to `polygon`. Base URL `https://api.massive.com`.
- Auth: `RESTClient(api_key=...)` sends `Authorization: Bearer <key>`.
- Rate limits: free tier 5 req/min → poll every 15 s. Paid tiers → 2-5 s.
- **One endpoint does the work.** `get_snapshot_all(market_type=STOCKS, tickers=[...])` returns every requested ticker in a *single* call, which is what keeps a 10-ticker watchlist inside the free tier's 5 req/min.
- A second endpoint, `get_snapshot_ticker(...)`, fetches one symbol on demand — used only by `ensure_priced`.

REST polling is deliberate rather than WebSocket streaming: it is simpler and works on all account tiers.

---

## 2. Response Shape

Relevant response fields per snapshot:

```json
{
  "ticker": "AAPL",
  "day":        { "previous_close": 129.61, "change_percent": -3.50, "volume": 111237700 },
  "last_trade": { "price": 125.07, "size": 100, "timestamp": 1675190399000 }
}
```

We read `last_trade.price` and `last_trade.timestamp` (Unix **milliseconds** → divide by 1000).

`day.previous_close` is not used today. If the frontend ever needs day-over-day change, that is the field to populate a `previous_close` on `PriceUpdate` from — see [`market_interface.md` §1](market_interface.md#why-its-shaped-this-way).

---

## 3. Implementation — `massive_client.py`

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

The `RESTClient` is synchronous, so every call is wrapped in `asyncio.to_thread` to keep the event loop free. That worker-thread write is exactly why `PriceCache` uses a `threading.Lock` rather than an asyncio primitive.

---

## 4. Ticker Management

| Operation | Behaviour | Latency to a price |
|---|---|---|
| `start(tickers)` | Sets the polled list and performs an immediate first poll, so the cache is warm on return | one round trip |
| `add_ticker(t)` | Normalizes and appends to the polled list. Fire-and-forget — **no price on return** | up to `poll_interval` |
| `remove_ticker(t)` | Normalizes, drops from the polled list, and evicts from the cache | n/a |
| `ensure_priced(t)` | Fetches that one symbol immediately with a timeout; joins the polled list only on success | one round trip, bounded by `timeout` |

The batch snapshot call means the polled list's length does not affect the number of API calls — one poll is one call regardless of whether 10 or 40 tickers are watched.

**Why `ensure_priced` is separate.** PLAN §8 requires a trade in an unpriced ticker to fill at execution time, but `add_ticker` alone can leave the caller waiting up to 15 seconds for a price that may never arrive (bad symbol). `ensure_priced` spends one extra API call to resolve that synchronously, with typed errors the route maps to a status code. Full rationale in [`market_interface.md` §3](market_interface.md#why-ensure_priced-exists).

**Rollback-free by construction.** A symbol joins `self._tickers` only *after* a price is confirmed and written to the cache. A failed lookup therefore leaves the polled set, the cache, and the watchlist exactly as they were — there is nothing to compensate for.

---

## 5. Poll Interval & Rate Limits

| Tier | Limit | `poll_interval` | Calls/min |
|---|---|---|---|
| Free | 5 req/min | `15.0` (default) | 4 |
| Starter / paid | effectively unlimited | `5.0` | 12 |
| Advanced | unlimited | `2.0` | 30 |

`ensure_priced` spends one extra call, so the free-tier default leaves a call of headroom per minute on purpose.

Because the batch endpoint collapses all tickers into one request, ticker count cannot trip the rate limit — only a too-short `poll_interval` can.

### Market-hours behaviour

Outside regular trading hours `last_trade.price` is the last print (possibly after-hours), so prices simply stop moving. This is correct and needs no special handling — but it is exactly why the SSE contract must re-emit `"flat"` ticks (see [`MARKET_DATA_DESIGN.md` §10.1](MARKET_DATA_DESIGN.md#101-why-the-stream-emits-unconditionally)) rather than falling silent, so the frontend keeps rendering and the connection indicator stays green.

---

## 6. Error Handling & Fallback Behaviour

The governing rule is invariant 4 from [`MARKET_DATA_DESIGN.md` §1](MARKET_DATA_DESIGN.md#1-architecture): the poll loop never raises. Every failure is logged and retried on the next interval, so a transient API problem degrades to stale prices rather than a dead backend.

**6.1 Invalid API key.** The first poll fails with 401, is logged, and the loop keeps retrying. The cache stays empty, so SSE emits nothing and the UI shows a connected-but-empty terminal. **Change required:** count consecutive poll failures and log an escalated `ERROR` after 3, naming 401 explicitly — a silent empty grid is the single most confusing failure mode in this app. Surfacing this through `/api/health` is a reasonable follow-on.

**6.2 Rate limiting (429).** Caught by the same handler and retried on the next interval. The batch snapshot endpoint means ticker count doesn't affect call count, so a user adding 30 tickers cannot trip the limit — only a too-short `MASSIVE_POLL_INTERVAL` can.

**6.3 Malformed snapshot.** A snapshot missing `last_trade` raises `AttributeError`/`TypeError`, is logged per ticker, and skipped; other tickers in the same batch still update.

**6.4 Trade against a stale price.** In Massive mode the cached price can be up to `poll_interval` old. This is accepted: no fees, no slippage, fake money. Worth stating in the UI as "prices delayed up to 15 s" when a key is configured.

**6.5 `ensure_priced` failures.** Classified rather than swallowed, because a user is waiting on a trade:

| Condition | Raised | HTTP |
|---|---|---|
| Bad shape (`NOT_A_STOCK`) | `InvalidSymbolFormatError` | 400 |
| HTTP 400/404, or "not found" in the message, or no `last_trade` | `UnknownSymbolError` | 400 |
| Timeout, network error, rate limit, source not started | `PricingUnavailableError` | 503 |

`_is_not_found` is a best-effort classifier: when in doubt it falls through to `PricingUnavailableError`, so an ambiguous failure is reported as retryable rather than permanently rejecting a symbol that may be perfectly valid.

**6.6 Fallback to the simulator.** There is no automatic runtime failover — the source is chosen once at startup by `create_market_data_source()`. Falling back to simulated prices mid-session would silently mix invented data into a real-data feed, which is worse than showing stale ones. To fall back, unset `MASSIVE_API_KEY` and restart.

---

## 7. Configuration

| Parameter | Location | Default | Description |
|---|---|---|---|
| `poll_interval` | `MassiveDataSource.__init__` | `15.0` s | Poll cadence; set from `MASSIVE_POLL_INTERVAL` |
| `timeout` | `ensure_priced` | `5.0` s | On-demand price fetch budget — one round trip with slack |

Environment variables (`MASSIVE_API_KEY`, `MASSIVE_POLL_INTERVAL`) and the source-selection rule are in [`MARKET_DATA_DESIGN.md` §14](MARKET_DATA_DESIGN.md#14-configuration); the factory that reads them is in [`market_interface.md` §5](market_interface.md#5-factory--factorypy).

---

## 8. Testing

Existing coverage: `test_massive.py`, 13 tests, 56% of `massive_client.py`. The gap is expected — the API methods are mocked, so the network paths are exercised only through the mock boundary. Mocks must set `source._client` and patch `_fetch_snapshots` / `_fetch_one` by name.

### `ensure_priced` leaves no residue on failure (new)

```python
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

Worth adding alongside it: a 404-shaped exception maps to `UnknownSymbolError`, a malformed snapshot in a batch does not stop sibling tickers updating, and a poll raising does not kill `_poll_loop`.
