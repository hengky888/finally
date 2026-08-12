# Market Data Backend — Architecture & Design

Overall design of record for the FinAlly market data subsystem: how the pieces fit together, how the subsystem is wired into FastAPI, how prices reach the browser over SSE, and how the watchlist and trade routes coordinate with it.

Everything described here lives under `backend/app/market/`.

**Status.** Most of this subsystem is already built and tested. This document describes the as-built architecture and specifies the changes needed to close contract gaps found in review. Each snippet is labelled **as built** or **change required** so an implementing agent knows what to write. See [`market_data_summary.md`](market_data_summary.md) for status, open gaps, and the recommended implementation order.

## Companion documents

| Document | Covers |
|---|---|
| [`market_interface.md`](market_interface.md) | `PriceUpdate`, `PriceCache`, the `MarketDataSource` ABC, error types, the factory, public API |
| [`market_simulator.md`](market_simulator.md) | GBM math, seed prices, symbol validation, `GBMSimulator`, `SimulatorDataSource`, simulator tests |
| [`massive_api.md`](massive_api.md) | Massive (Polygon.io) REST integration, polling, rate limits, error handling, fallback |
| [`market_data_summary.md`](market_data_summary.md) | Executive summary, implementation status, key decisions, unresolved gaps, delivery order |

---

## Table of Contents

1. [Architecture](#1-architecture)
2. [File Structure](#2-file-structure)
3. [SSE Streaming — `stream.py`](#3-sse-streaming--streampy)
4. [FastAPI Lifecycle Integration](#4-fastapi-lifecycle-integration)
5. [Watchlist & Trade Coordination](#5-watchlist--trade-coordination)
6. [Cross-Cutting Error Handling & Edge Cases](#6-cross-cutting-error-handling--edge-cases)
7. [Environment Configuration](#7-environment-configuration)
8. [Streaming & End-to-End Testing](#8-streaming--end-to-end-testing)

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

The selection is made by `create_market_data_source()` — see [`market_interface.md`](market_interface.md#5-factory--factorypy).

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

`__init__.py` re-exports the public API so the rest of the backend never reaches into submodules; the export list is specified in [`market_interface.md`](market_interface.md#6-public-api--__init__py).

---

## 3. SSE Streaming — `stream.py`

### 3.1 The contract gap

PLAN §6 promises: *"The stream re-emits every priced ticker each tick, including unchanged ones (`flat`)."* The shipped generator instead gates on `PriceCache.version` and only yields when the cache changed. In simulator mode that's invisible (the cache changes every 500 ms). In **Massive mode it means the stream emits nothing for 15 seconds at a time** — the frontend can't distinguish a quiet market from a dead connection, and `REVIEW.md` flags it as a P1 contract break.

Second, subtler problem: `PriceUpdate.direction` is relative to the last *cache write*. Re-emitting a cached update between Massive polls would repeat `"up"` every tick, and the frontend would flash the row green twice a second for 15 seconds on a single real uptick.

**Resolution — emit unconditionally, compute direction per connection.** Every `interval`, send a snapshot of every priced ticker. Each connection remembers the last price it sent for each ticker and derives `direction`/`change` against *that*, so `direction` answers exactly the question the frontend asks: "did this change since the last event I received?" A ticker that didn't move reports `"flat"` with `change: 0.0` and triggers no animation.

### 3.2 Payload

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

### 3.3 Implementation

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

### 3.4 Client usage

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

## 4. FastAPI Lifecycle Integration

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

## 5. Watchlist & Trade Coordination

### 5.1 Add to watchlist

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

### 5.2 Remove from watchlist

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

### 5.3 Trade execution

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

### 5.4 LLM-issued trades

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

## 6. Cross-Cutting Error Handling & Edge Cases

Source-specific failure modes live with their source: see [`massive_api.md`](massive_api.md#6-error-handling--fallback-behaviour) for API-key, rate-limit, malformed-snapshot, and stale-price handling, and [`market_simulator.md`](market_simulator.md#8-non-psd-correlation-matrix) for the non-PSD correlation matrix.

**6.1 Empty watchlist at startup.** `start([])` is valid. The simulator's `step()` returns `{}`; the Massive poller skips its API call. The SSE loop yields nothing until a ticker exists (the `if prices:` guard), then resumes. Adding a ticker recovers immediately.

**6.2 Cache miss on a held position.** Shouldn't happen — startup unions positions into the priced set (§4). If it does (e.g., a Massive symbol that stopped returning trades), portfolio valuation must treat the position as `None`-priced and exclude it from `total_value` rather than valuing it at zero, which would show a fake catastrophic loss.

**6.3 Lock contention.** At 10 tickers × 2 Hz, plus one `get_all()` per SSE client per tick, the critical section is a dict copy of ~10 entries. Negligible. A read-write lock would be the fix if this ever mattered; it won't at this scale.

**6.4 Clock source for `timestamp`.** Simulator timestamps come from `time.time()` (wall clock); Massive timestamps come from the exchange. Both are Unix seconds, so the frontend can plot them on one axis, but Massive timestamps can appear slightly stale relative to local time. Don't compute "data age" by subtracting them from `Date.now()` and alarming the user.

---

## 7. Environment Configuration

The deployment-facing surface is two environment variables. Per-component tuning parameters are documented with their component.

| Variable | Default | Description |
|---|---|---|
| `MASSIVE_API_KEY` | `""` | Non-empty → Massive API; otherwise the GBM simulator |
| `MASSIVE_POLL_INTERVAL` | `15.0` s | Massive poll cadence (**change required** — see [`massive_api.md`](massive_api.md#5-poll-interval--rate-limits)) |

| In-code parameter | Location | Default | Description |
|---|---|---|---|
| `interval` | `create_stream_router` | `0.5` s | SSE emit cadence |
| retry directive | `_generate_events` | `1000` ms | EventSource reconnect delay |

Simulator parameters (`update_interval`, `event_probability`, `dt`) are in [`market_simulator.md`](market_simulator.md#9-configuration); Massive parameters (`poll_interval`, `ensure_priced` `timeout`) are in [`massive_api.md`](massive_api.md#7-configuration).

---

## 8. Streaming & End-to-End Testing

Per-component test plans live in [`market_interface.md`](market_interface.md#7-conformance--cache-testing), [`market_simulator.md`](market_simulator.md#10-testing), and [`massive_api.md`](massive_api.md#8-testing). Existing coverage is tabulated in [`market_data_summary.md`](market_data_summary.md#test-suite).

### 8.1 SSE contract tests

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

### 8.2 E2E hooks (`test/`)

- Fresh start: 10 tickers appear with prices within 2 s.
- Prices visibly change over 5 s (simulator mode).
- SSE resilience: kill the connection, confirm `EventSource` reconnects and prices resume.
- Add `PYPL` via the trade bar with no prior watchlist entry → position appears, ticker joins the watchlist.
- Trade `NOT_A_STOCK` → 400 with a readable message, no watchlist row created.
