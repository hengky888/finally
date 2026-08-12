# Market Data Backend — Summary

**Status:** Built, tested, and reviewed. The shipped code passes 73 tests at 84% coverage. Three contract gaps found in review are specified but **not yet implemented** — see [Unresolved gaps](#unresolved-gaps) and [Recommended implementation order](#recommended-implementation-order).

This is the entry point for the market data documentation set. Design detail lives in the companion documents:

| Document | Covers |
|---|---|
| [`MARKET_DATA_DESIGN.md`](MARKET_DATA_DESIGN.md) | **Consolidated design of record** — architecture, all nine modules, SSE streaming, FastAPI lifecycle, watchlist/trade coordination, edge cases, testing |
| [`market_interface.md`](market_interface.md) | `PriceUpdate`, `PriceCache`, the `MarketDataSource` ABC, error taxonomy, factory, public API |
| [`market_simulator.md`](market_simulator.md) | GBM math, seed prices, symbol validation, `GBMSimulator`, `SimulatorDataSource`, simulator tests |
| [`massive_api.md`](massive_api.md) | Massive (Polygon.io) REST integration, polling, ticker management, rate limits, error handling, fallback |

Earlier drafts are in [`archive/`](archive/).

---

## What Was Built

A complete market data subsystem in `backend/app/market/` (8 modules, ~500 lines) providing live price simulation and real market data via a unified interface.

### Architecture

```
MarketDataSource (ABC)
├── SimulatorDataSource  →  GBM simulator (default, no API key needed)
└── MassiveDataSource    →  Polygon.io REST poller (when MASSIVE_API_KEY set)
        │
        ▼
   PriceCache (thread-safe, in-memory)
        │
        ├──→ SSE stream endpoint (/api/stream/prices)
        ├──→ Portfolio valuation
        └──→ Trade execution
```

### Modules

| File | Purpose | Status |
|------|---------|--------|
| `models.py` | `PriceUpdate` — immutable frozen dataclass (ticker, price, previous_price, timestamp, change, direction) | Complete |
| `interface.py` | `MarketDataSource` — ABC defining `start/stop/add_ticker/remove_ticker/get_tickers` | Needs `ensure_priced` + error types |
| `cache.py` | `PriceCache` — thread-safe price store with a version counter | Needs a lock on `version` |
| `seed_prices.py` | Realistic seed prices, per-ticker GBM params (drift/volatility), correlation groups | Complete |
| `simulator.py` | `GBMSimulator` (GBM with Cholesky-correlated moves) + `SimulatorDataSource` | Needs `ensure_priced` + PSD fallback |
| `massive_client.py` | `MassiveDataSource` — REST polling client for Polygon.io via the `massive` package | Needs `ensure_priced` + failure escalation |
| `factory.py` | `create_market_data_source()` — selects simulator or Massive from `MASSIVE_API_KEY` | Needs `MASSIVE_POLL_INTERVAL` |
| `symbols.py` | Symbol normalization + simulated universe validation | **Not yet written** |
| `stream.py` | `create_stream_router()` — FastAPI SSE endpoint factory | Needs rewrite (cadence contract) |

---

## Key Design Decisions

- **Strategy pattern** — both data sources implement the same ABC; downstream code is source-agnostic.
- **PriceCache as single point of truth** — producers write, consumers read; no direct coupling. The cache rounds to 2 decimals on write, so the fill price a trade executes at is identical to the price the user saw stream past.
- **Priced set = `watchlist ∪ open positions`** — a held ticker stays priced after leaving the watchlist, so the portfolio can always be valued.
- **GBM with correlated moves** — Cholesky decomposition of a sector-based correlation matrix; tech correlates at 0.6, finance at 0.5, cross-sector at 0.3.
- **Random shock events** — ~0.1% chance per tick per ticker of a 2-5% move for visual drama.
- **SSE over WebSockets** — simpler, one-way push, universal browser support.
- **REST polling for Massive, not WebSocket** — works on all account tiers; one batch snapshot call covers the whole watchlist, so ticker count never affects rate-limit headroom.
- **Background loops never raise** — a failed tick or poll is logged and retried, because a dead task means prices silently freeze.
- **No runtime failover between sources** — the source is chosen once at startup; mixing invented prices into a real feed would be worse than showing stale ones.

---

## Test Suite

**73 tests, all passing.** 6 test modules in `backend/tests/market/`. Overall coverage: 84%.

| Module | Tests | Coverage |
|--------|-------|----------|
| `test_models.py` | 11 | `models.py`: 100% |
| `test_cache.py` | 13 | `cache.py`: 100% |
| `test_simulator.py` | 17 | `simulator.py`: 98% |
| `test_simulator_source.py` | 10 | (integration tests) |
| `test_factory.py` | 7 | `factory.py`: 100% |
| `test_massive.py` | 13 | `massive_client.py`: 56% (expected — API methods mocked) |

`stream.py` sits at 31% with no dedicated tests, which is the largest coverage gap and the one that matters most: it is the frontend's entire contract.

---

## Code Review & Fixes Applied

An earlier code review identified 7 issues. All were resolved in the shipped code:

1. **pyproject.toml build config** — added `[tool.hatch.build.targets.wheel] packages = ["app"]`
2. **Lazy imports removed** — `massive` is a core dependency; imports moved to top level
3. **SSE return type fixed** — `_generate_events` annotated as `AsyncGenerator[str, None]`
4. **Public `get_tickers()`** — added to `GBMSimulator` to avoid private attribute access
5. **Correlation constants cleaned up** — removed unused `DEFAULT_CORR`, consolidated into `CROSS_GROUP_CORR`
6. **Unused test imports removed** — `pytest`, `math`, `asyncio` cleaned from 4 test files
7. **Massive test mocks fixed** — `source._client` set in tests, patches target correct names

---

## Unresolved Gaps

Three findings from `REVIEW.md` remain open in the code. Each now has one implementable behaviour specified in the design documents, rather than a list of options.

**1. SSE cadence contradicts the plan (P1).** PLAN §6 promises every priced ticker re-emitted each tick including `"flat"`, but the shipped generator gates on `PriceCache.version`. In Massive mode the stream emits nothing for up to 15 seconds and the frontend cannot distinguish a quiet market from a dead connection. A subtler bug sits behind it: `PriceUpdate.direction` is relative to the last *cache write*, so naively re-emitting a cached update would repeat `"up"` twice a second for the whole inter-poll gap and flash the row green throughout.
→ **Resolution:** emit unconditionally; compute `direction` per connection against the last price that connection was sent; move the payload to a `{seq, ts, prices}` envelope. Specified in [`MARKET_DATA_DESIGN.md` §10](MARKET_DATA_DESIGN.md#10-sse-streaming--streampy).

**2. Unpriced ticker fills are undefined (P1).** PLAN §8 says a trade in an unpriced ticker auto-adds it and fills from cache, but Massive's `add_ticker` only appends to a list and waits for the next poll. The review also asked whether the automatic watchlist addition is rolled back on failure.
→ **Resolution:** add `ensure_priced(ticker, timeout)` to the interface with typed `UnknownSymbolError` (400, permanent) and `PricingUnavailableError` (503, transient). It is rollback-*free* by construction: the symbol joins the polled set only after a price is confirmed, and the watchlist row is written only after the trade succeeds. Specified in [`market_interface.md` §3](market_interface.md#3-unified-interface--interfacepy).

**3. No source-independent symbol validation (P2).** The simulator currently assigns `NOT_A_STOCK` a random $50-300 price and lets it be traded.
→ **Resolution:** add `symbols.py` with shape validation (both modes) plus a curated `SIMULATED_UNIVERSE`, applied before either the data source or the watchlist is mutated. The trade-off is deliberate: the simulator is stricter than Massive about genuinely obscure real symbols, which is the right bias for a demo that must never show a plausible price for a company that doesn't exist. Specified in [`market_simulator.md` §5](market_simulator.md#5-symbol-validation--symbolspy).

Smaller open items — an unlocked `version` read, a non-PSD correlation matrix crashing a request, no `MASSIVE_POLL_INTERVAL` env override, and silent repeated Massive poll failures — are covered in the order below.

---

## Recommended Implementation Order

Everything an implementing agent needs to change, in dependency order.

| # | Change | Files | Closes |
|---|---|---|---|
| 1 | Add `symbols.py`: `normalize_symbol`, `SIMULATED_UNIVERSE`, `is_simulated` | `symbols.py` (new) | REVIEW P2 "source-independent ticker validation" |
| 2 | Add `UnknownSymbolError` / `PricingUnavailableError` and the `ensure_priced` abstract method | `interface.py` | REVIEW P1 "unpriced Massive ticker fill" |
| 3 | Implement `ensure_priced` in both sources; normalize symbols in `add_ticker`/`remove_ticker` | `simulator.py`, `massive_client.py` | same |
| 4 | Rewrite the SSE generator: emit every tick, per-connection direction, `{seq, ts, prices}` envelope; build a fresh `APIRouter` per call | `stream.py` | REVIEW P1 "SSE cadence"; `archive/MARKET_DATA_REVIEW.md` §3.6 |
| 5 | Lock the `version` property | `cache.py` | `archive/MARKET_DATA_REVIEW.md` §3.4 |
| 6 | Fall back to independent draws on `LinAlgError` | `simulator.py` | [`market_simulator.md` §8](market_simulator.md#8-non-psd-correlation-matrix) |
| 7 | Read `MASSIVE_POLL_INTERVAL` from env | `factory.py` | [`massive_api.md` §5](massive_api.md#5-poll-interval--rate-limits) |
| 8 | Escalate repeated Massive poll failures to `ERROR` after 3 consecutive | `massive_client.py` | [`massive_api.md` §6](massive_api.md#6-error-handling--fallback-behaviour) |
| 9 | Add tests: symbols, `ensure_priced`, SSE contract, cache concurrency, full-watchlist Cholesky | `tests/market/` | `archive/MARKET_DATA_REVIEW.md` §4.2 |

Items 1-4 are prerequisites for the portfolio and chat work: the trade route cannot be written without `ensure_priced`, and the frontend cannot be written against a stream whose cadence is undefined. Items 5-8 are independent hardening and can land any time.

`PriceUpdate`, `PriceCache`, `GBMSimulator`, the factory's selection logic, and the Massive polling loop are otherwise unchanged.

---

## Demo

A Rich terminal demo is available at `backend/market_data_demo.py`:

```bash
cd backend
uv run market_data_demo.py
```

Displays a live-updating dashboard with all 10 tickers, sparklines, color-coded direction arrows, and an event log for notable price moves. Runs 60 seconds or until Ctrl+C.

---

## Usage for Downstream Code

Everything the rest of the backend needs is re-exported from `app.market`: `PriceCache`, `PriceUpdate`, `MarketDataSource`, `UnknownSymbolError`, `PricingUnavailableError`, `create_market_data_source`, `create_stream_router`, and `normalize_symbol`.

The startup/read/shutdown walkthrough and the full method-by-method contract are in [`market_interface.md` §6](market_interface.md#6-public-api--__init__py). Route-level wiring — lifespan startup, the SSE router, and the watchlist/trade handlers — is in [`MARKET_DATA_DESIGN.md` §11-12](MARKET_DATA_DESIGN.md#11-fastapi-lifecycle-integration).
