# Market Data Backend — Code Review

**Date:** 2026-08-12
**Branch reviewed:** `office-development` @ `b45d882`
**Scope:** `backend/app/market/` (10 modules, 913 lines), `backend/tests/market/` (8 modules, 127 tests)

Every finding below was verified by execution — tests run, code paths exercised, the SSE endpoint driven over a real socket. Where a claim is empirical the evidence is quoted.

---

## 1. Test & Tooling Results

```
127 passed in 3.57s
```

| Module | Stmts | Miss | Cover | Uncovered |
|---|---|---|---|---|
| `cache.py` | 40 | 0 | **100%** | |
| `factory.py` | 16 | 0 | **100%** | |
| `interface.py` | 17 | 0 | **100%** | |
| `models.py` | 26 | 0 | **100%** | |
| `seed_prices.py` | 8 | 0 | **100%** | |
| `symbols.py` | 12 | 0 | **100%** | |
| `stream.py` | 47 | 1 | 98% | 36 |
| `simulator.py` | 158 | 7 | 96% | 150, 175–179, 286, 297–298 |
| `massive_client.py` | 104 | 6 | 94% | 131–133, 170, 181, 188 |
| **TOTAL** | **435** | **14** | **97%** | |

No deprecation warnings (the 73 `DefaultEventLoopPolicy` warnings noted in `backend/planning/REVIEW.md` no longer reproduce here on Python 3.13.7).

**SSE verified end-to-end.** There is still no FastAPI app in the repo (§3.1), so a probe app was built per `PLAN.md` §10 and served under real uvicorn. 10 `data:` frames in 5 seconds — the specified ~500 ms cadence — with the current envelope:

```
retry: 1000

data: {"seq": 1, "ts": 1786524427.628691, "prices": {"AAPL": {"ticker": "AAPL",
       "price": 190.0, "previous_price": 190.0, "change": 0.0, "change_percent": 0.0,
       "direction": "flat", "timestamp": 1786524427.5437129}, ...}}
```

---

## 2. Resolved Since `main`

This branch is 18 commits ahead of `main` and closes most of what the previous review round raised. Recording it so these aren't re-reported:

- **Module-level router → fixed.** `create_stream_router()` now builds a fresh `APIRouter` per call (`stream.py:25`), with the rationale in the docstring. Double registration is gone.
- **SSE had no tests → fixed.** `test_stream.py` adds 14 tests; `stream.py` went 33% → 98%.
- **No heartbeat → largely fixed.** The version gate is gone; `_generate_events` now emits every priced ticker every tick including unchanged ones as `"flat"` (`stream.py:70–108`). One residual gap remains — see §3.4.
- **Inconsistent ticker normalization → fixed.** Both sources now route through `normalize_symbol()` (`simulator.py:250,260`, `massive_client.py:71,77`).
- **`version` read outside the lock → fixed** (`cache.py:67`).
- **`README.md` setup commands → fixed** — now `uv sync --extra dev`.
- **Unpriced-ticker trade gap → fixed.** New `ensure_priced()` on the ABC, with `UnknownSymbolError` (→400) and `PricingUnavailableError` (→503). Massive fetches a single symbol on demand and joins the polled set *only on success* (`massive_client.py:85–125`) — no residue to roll back. Good design.
- **Symbol validation → added** (`symbols.py`), though only on one of two paths — see §3.2.
- **Cholesky robustness → improved.** `LinAlgError` is now caught and falls back to independent draws (`simulator.py:173–179`) rather than freezing the feed.
- **Massive failure escalation → added** (`_consecutive_failures`, `massive_client.py:169`), plus a configurable `MASSIVE_POLL_INTERVAL` (`factory.py:27`).
- **`CancelledError` now re-raised** after logging (`stream.py:111`), so cancellation propagates correctly.

---

## 3. Findings

### 3.1 Still no FastAPI application (Severity: High)

`backend/app/` contains only `__init__.py` and `market/`. Verified: `grep -rn "FastAPI(" backend/ --include=*.py` returns **nothing** outside tests.

Consequences unchanged from the last round: `create_stream_router()` has zero production callers, `/api/stream/prices` is not served by anything in the repo, no `lifespan` wiring exists, nothing calls `load_dotenv()` so `MASSIVE_API_KEY` from the project-root `.env` (`PLAN.md` §5) is never read, `/api/health` (`PLAN.md` §8) is absent, and logging is never configured — so every `logger.info` in this subsystem is silently dropped under a stock uvicorn launch.

The market data layer is a well-built library that nothing instantiates. Everything downstream blocks on this.

### 3.2 `add_ticker()` bypasses the simulated universe that `ensure_priced()` enforces (Severity: High)

`symbols.py` exists to stop invented prices for symbols the market doesn't trade. It is wired into `ensure_priced()` (`simulator.py:276`) but **not** into `add_ticker()`. Verified:

```
is_simulated('ZZZZZ')   = False          (valid format, outside the universe)
ensure_priced('ZZZZZ')  -> rejected: UnknownSymbolError     ✓
add_ticker('ZZZZZ')     -> tickers=['AAPL', 'ZZZZZ']
                           cached price = 270.69            ✗ invented
```

`GBMSimulator._add_ticker_internal` still assigns `random.uniform(50.0, 300.0)` to any unrecognized symbol (`simulator.py:152`), and nothing on the `add_ticker` path checks `is_simulated()`.

This matters because `POST /api/watchlist` (`PLAN.md` §8) is an `add_ticker` caller, not an `ensure_priced` caller. So the trade path is protected while the watchlist path is not: a user or the LLM can add `ZZZZZ` to the watchlist and it will stream a fabricated price at $270.69 indefinitely. This is precisely the `[P2] Add source-independent symbol validation` finding in `backend/planning/REVIEW.md` — closed for trades, still open for the watchlist.

**Fix:** gate `SimulatorDataSource.add_ticker()` on `is_simulated()` too, raising `UnknownSymbolError`, so both entry points enforce one contract.

### 3.3 GBM `dt` is still decoupled from the tick interval (Severity: High)

Unchanged from the previous review. `SimulatorDataSource.__init__` accepts `update_interval` but never passes a matching `dt` to `GBMSimulator`, which keeps the class constant tuned for 500 ms ticks. Verified — `SimulatorDataSource.start` contains no `dt=` argument, and `DEFAULT_DT` remains `8.4792e-08`.

At `update_interval=0.05` the simulation advances **10× faster than wall clock**; volatility, drift and shock frequency all silently mis-scale. The default (0.5) happens to line up, so nothing looks broken, but the two numbers must agree and nothing enforces it. Several tests in `test_simulator_source.py` already run at 0.05/0.01 and are therefore exercising a mis-scaled model.

**Fix:** derive it — `dt = update_interval / GBMSimulator.TRADING_SECONDS_PER_YEAR` — and pass it through.

### 3.4 The stream goes silent on an empty priced set, contradicting its own contract (Severity: Medium)

`_generate_events` documents its purpose as keeping the stream alive so *"the client can treat silence as a genuine connection problem"* (`stream.py:32–34, 77–79`). But the emit is guarded:

```python
if prices:
    seq += 1
    payload = json.dumps({"seq": seq, "ts": time.time(), "prices": prices})
    yield f"data: {payload}\n\n"
```

With zero priced tickers — an empty watchlist with no open positions, which `PLAN.md` §13.1 treats as a supported state — the generator emits `retry: 1000` and then nothing, ever. That is exactly the silence the design says must mean a broken connection, produced by a perfectly healthy one. A client showing the red/yellow connection dot from `PLAN.md` §2 would report a false disconnect.

**Fix:** drop the `if prices:` guard and emit `"prices": {}`, or send a `: keepalive\n\n` comment on empty ticks.

### 3.5 "Daily change %" is still unavailable to the frontend (Severity: Medium)

`PLAN.md:381` still requires the watchlist to show *"daily change %"*. Nothing in this subsystem can supply it.

`_diff()` computes `change` and `change_percent` relative to *the last price this connection was sent* (`stream.py:49–67`) — a per-connection tick delta. That is a genuine improvement for flash animations (each client gets a correct up/down regardless of when it connected), but it is further from a daily figure than before, not closer: it now depends on connection age. No session-open or previous-close price is stored by `PriceUpdate`, `PriceCache`, or either source.

The frontend cannot derive it either — `PLAN.md:381–382` is explicit that sparklines and charts accumulate from SSE since page load with no historical backfill. Worth noting the data already exists unused on the Massive side: `TickerSnapshot` exposes `todays_change_percent` and `prev_day`, and `_poll_once` reads only `last_trade`.

**Fix:** carry a per-ticker reference price (seed price for the simulator, `prev_day.close` for Massive) and expose `daily_change_percent` in the payload.

### 3.6 The SSE envelope is undocumented in the shared contract (Severity: Medium)

The wire format is now `{"seq": int, "ts": float, "prices": {ticker: {...}}}`. `PLAN.md` §6 documents the per-ticker fields and the re-emit-every-tick behaviour, but says nothing about the `seq`/`ts`/`prices` wrapper. `PLAN.md` is the stated frontend/backend contract, and a frontend written against §6 as literally worded would parse the payload as a flat ticker map and break.

Two semantics also need pinning down before the frontend relies on them: `seq` is **per-connection** and restarts at 1 on every reconnect, so it cannot be used for gap detection across a reconnect; and `ts` (server send time) differs from each ticker's own `timestamp` (trade time), which in Massive mode can be many seconds older.

### 3.7 `PriceCache.version` is now dead production code (Severity: Low)

Verified: `grep -rn "\.version" app/` returns **no** matches — the only remaining references are in `test_cache.py` and `test_simulator_source.py`. The stream dropped version gating in favour of unconditional emission, which removed the counter's sole consumer.

Related: `remove()` still doesn't bump `_version` (`cache.py:59–62`). Harmless today precisely because nothing reads it — but the latent bug returns intact the moment anything re-adopts version-based change detection. Either delete the counter, or fix `remove()` and document what it's for.

### 3.8 Lower-severity items

- **`ts = timestamp or time.time()`** (`cache.py:30`) — a legitimate `timestamp=0.0` is silently replaced with wall-clock. Should be `if timestamp is None`.
- **Live ticker list handed to a worker thread** (`massive_client.py:183`) — `_fetch_snapshots` runs under `asyncio.to_thread` and passes `self._tickers`, which the SDK iterates via `",".join(...)`, while `add_ticker`/`remove_ticker`/`ensure_priced` mutate that same list on the event loop. Narrow but real; pass `list(self._tickers)`.
- **`Connection: keep-alive`** (`stream.py:41`) — hop-by-hop header; ignored on HTTP/1.1, illegal under HTTP/2.
- **`is_simulated()` docstring** (`symbols.py:54`) — "has (or can invent) a defensible price" describes the opposite of its purpose; it is a pure membership test whose job is to *prevent* invention.
- **`_is_not_found` treats HTTP 400 as unknown-symbol** (`massive_client.py:197`) — 400 also covers malformed requests, so a client-side bug would surface to the user as "not a recognized symbol" and never be retried.
- **`add_ticker` before `start()`** (`simulator.py:249–257`) — normalizes, then silently does nothing when `self._sim is None`. A no-op that looks like success.
- **`conftest.py`'s `event_loop_policy` fixture** is a no-op override under pytest-asyncio 1.3 and can be deleted.
- **RNG is unseeded** — no way to make the simulator deterministic. `PLAN.md` §12 calls for reproducible E2E tests; a `seed` parameter on `GBMSimulator` is worth adding before that work starts.

---

## 4. Verdict

This branch is a marked improvement over `main`. The router bug is fixed, SSE is properly tested at 98% coverage, symbol handling is unified behind `normalize_symbol()`, and the `ensure_priced()` design — with its permanent/transient error split and join-only-on-success semantics — is a genuinely good answer to the trade-pricing gap. Overall coverage is 97% across 127 passing tests.

Two things stand between it and being ready to build on.

**Fix before building on this:**
1. Write `backend/app/main.py` — lifespan wiring, `.env` loading, `/api/health`, logging configuration (§3.1).
2. Enforce the simulated universe on `add_ticker()`, not just `ensure_priced()` (§3.2) — today the watchlist path can stream invented prices for symbols that don't exist.
3. Derive `dt` from `update_interval` (§3.3).

**Fix before the frontend is built against this:**
4. Emit on empty ticks so silence keeps meaning "disconnected" (§3.4).
5. Decide how `daily change %` is sourced (§3.5) — `PLAN.md:381` requires it and nothing can currently supply it.
6. Document the `{seq, ts, prices}` envelope in `PLAN.md` §6, including that `seq` resets per connection (§3.6).

**Cleanup:**
7. Resolve `PriceCache.version` — delete it or fix `remove()` and document its purpose (§3.7).
8. The items in §3.8.
