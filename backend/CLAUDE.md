# Backend — Developer Guide

## Project Setup

```bash
cd backend
uv sync --extra dev   # Install all dependencies including test/lint tools
```

## Running the App

```bash
uv run --extra dev uvicorn app.main:app --reload --port 8000
```

`app/main.py` owns process-wide concerns the `app.market` package deliberately
does not: loading `.env` from the project root, configuring logging (without
which every `logger.info` in `app.market` is silently discarded), and running the
market data source for the lifetime of the app.

- `GET /api/health` → `{"status": "ok", "priced_tickers": N}`
- `GET /api/stream/prices` → SSE price stream

Downstream routers get the shared objects via dependency injection:

```python
from app.main import get_price_cache, get_market_source

@router.post("/api/portfolio/trade")
async def trade(cache: PriceCache = Depends(get_price_cache)): ...
```

Startup tickers come from `load_initial_tickers()` — currently the seed
watchlist; point it at the database when that lands. `LOG_LEVEL` (default
`INFO`) controls verbosity.

## Market Data API

The market data subsystem lives in `app/market/`. Use these imports:

```python
from app.market import PriceCache, PriceUpdate, MarketDataSource, create_market_data_source
```

### Core Types

- **`PriceUpdate`** — Immutable dataclass: `ticker`, `price`, `previous_price`, `timestamp`, `reference_price`, plus properties `change`, `change_percent`, `direction` ("up"/"down"/"flat"), `daily_change`, `daily_change_percent`, and `to_dict()` for JSON serialization.

  Two different deltas, don't mix them up: `change_percent` is tick-over-tick (~0.005%, drives the flash animation); `daily_change_percent` is measured from `reference_price` and is what the watchlist's "daily change %" column shows.

- **`PriceCache`** — Thread-safe in-memory store. Key methods:
  - `update(ticker, price, timestamp=None) -> PriceUpdate`
  - `get(ticker) -> PriceUpdate | None`
  - `get_price(ticker) -> float | None`
  - `get_all() -> dict[str, PriceUpdate]`
  - `set_reference(ticker, price)` — anchor for `daily_change_percent`; defaults to the first price seen
  - `remove(ticker)`
  - `version` property — monotonic counter, bumped on every mutation including removals

- **`MarketDataSource`** — Abstract interface implemented by `SimulatorDataSource` and `MassiveDataSource`. Lifecycle: `start(tickers)` -> `add_ticker()` / `remove_ticker()` -> `stop()`, plus `ensure_priced(ticker)` when a trade needs a price immediately.

  Both implementations normalize symbols and enforce a universe: `add_ticker()` and `ensure_priced()` raise `UnknownSymbolError` (→ HTTP 400) for symbols the source cannot price, and `PricingUnavailableError` (→ HTTP 503) for transient failures. Never assume an arbitrary string will be priced.

- **`SimulatorDataSource(cache, update_interval=0.5, seed=None)`** — pass `seed` for a reproducible price path in tests. The GBM time step is derived from `update_interval`, so changing the tick rate keeps volatility correctly scaled.

- **`create_market_data_source(cache)`** — Factory. Returns `MassiveDataSource` if `MASSIVE_API_KEY` is set, otherwise `SimulatorDataSource`.

### SSE Streaming

```python
from app.market import create_stream_router

router = create_stream_router(price_cache)  # Returns FastAPI APIRouter
# Endpoint: GET /api/stream/prices (text/event-stream)
```

### Seed Data

Default tickers: AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX. Seed prices and per-ticker volatility/drift params are in `app/market/seed_prices.py`.

## Running Tests

```bash
uv run --extra dev pytest -v              # All tests
uv run --extra dev pytest --cov=app       # With coverage
uv run --extra dev ruff check app/ tests/ # Lint
```

## Demo

```bash
uv run market_data_demo.py   # Live terminal dashboard with simulated prices
```
