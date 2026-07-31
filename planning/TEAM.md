# FinAlly Build Team — Working Agreement

The shared contract for the agent team completing FinAlly. `planning/PLAN.md` is the
specification; this file is the coordination layer on top of it.

## Rules for every team member

1. **Stay inside your write zone.** The ownership map below is exclusive. If you believe a
   file outside your zone must change, stop and report it to the team lead instead of
   editing it.
2. **Do not edit `backend/pyproject.toml` or `backend/uv.lock`.** All dependencies are
   already installed: `fastapi`, `uvicorn`, `numpy`, `massive`, `rich`, `litellm`,
   `python-dotenv`, and dev extras `pytest`, `pytest-asyncio`, `pytest-cov`, `pytest-mock`,
   `httpx`, `ruff`. Need another? Ask the lead.
3. **Do not modify `backend/app/market/`.** The market data subsystem is complete and has
   127 passing tests. Consume it; do not change it.
4. **Do not run `git commit`, `git push`, or `git checkout`.** The lead handles version
   control.
5. **Work incrementally.** Small steps, run tests after each one, only move on when green.
6. **Follow the repo style rules** in `CLAUDE.md` and `backend/CLAUDE.md`: no
   overengineering, no defensive programming, no emojis in code or logs, short functions,
   clear names, concise docstrings, sparing comments.
7. **Never weaken a test to make it pass.** If a test is wrong, say so and explain why.
8. **Regression bar:** `cd backend && uv run --extra dev pytest -q` must stay fully green.
   You are done only when it is.

## Ownership map

| Member | Exclusive write zone |
|---|---|
| Database Engineer | `backend/app/db/**`, `backend/tests/db/**` |
| Backend API Engineer | `backend/app/api/**`, `backend/app/services/**`, `backend/app/main.py`, `backend/app/config.py`, `backend/tests/api/**`, `backend/tests/services/**` |
| LLM Engineer | `backend/app/llm/**`, `backend/tests/llm/**` |
| Frontend Engineer | `frontend/**` |
| DevOps Engineer | `Dockerfile`, `.dockerignore`, `scripts/**`, `.env.example`, `db/.gitkeep` |
| Integration Tester | `test/**` |

Nobody owns `planning/**` or `README.md` — the lead updates those.

## Internal contracts

These signatures are frozen so members can build against each other in parallel. If you
need one changed, raise it with the lead rather than changing it unilaterally.

### Database layer — `backend/app/db/`

Plain `sqlite3` from the standard library. No ORM. Rows come back as `dict` (use
`sqlite3.Row` and convert), never raw tuples.

**Callers own the transaction.** Accessors do not commit. Wrap any unit of work that must
be all-or-nothing in `with conn:` — sqlite3 commits it on success and rolls it back on an
exception. This is not optional for `execute_trade`: the trade row, the position, the cash
balance, and the snapshot are one unit, and a partial write there debits a user's cash
without giving them the shares.

```python
with conn:
    trades.append(conn, ...)
    positions.upsert(conn, ...)
    profile.set_cash(conn, ...)
    snapshots.append(conn, ...)
```

```python
from app.db import init_db, get_connection
from app.db import profile, watchlist, positions, trades, snapshots, chat

init_db(path)                     # create schema + seed a fresh DB; idempotent.
                                  # Stores the path, so call it before get_connection().
get_connection()                  # -> sqlite3.Connection, row_factory set, no arguments.
                                  # Not thread-safe: open one per request/unit of work.

profile.get(conn)                 # -> {"id", "cash_balance", "created_at"}
profile.set_cash(conn, cash)      # -> None

watchlist.list_tickers(conn)      # -> list[str], insertion order
watchlist.add(conn, ticker)       # -> bool (False if already present)
watchlist.remove(conn, ticker)    # -> bool (False if absent)

positions.list_all(conn)          # -> list[dict] with ticker, quantity, avg_cost, updated_at
positions.get(conn, ticker)       # -> dict | None
positions.upsert(conn, ticker, quantity, avg_cost)
positions.delete(conn, ticker)

trades.append(conn, ticker, side, quantity, price)   # -> dict (the new row)
trades.list_recent(conn, limit=50)                   # -> list[dict], newest first

snapshots.append(conn, total_value)                  # -> dict
snapshots.list_all(conn)                             # -> list[dict], oldest first

chat.append(conn, role, content, actions=None)       # actions: dict | None, stored as JSON
chat.list_recent(conn, limit=20)                     # -> list[dict], oldest first, actions parsed
```

Schema is PLAN.md §7 verbatim. The profile table is named **`user_profile`** (singular) —
the plural `users_profile` in old drafts is dead. Every table carries `user_id` defaulting
to `"default"`; `app/db/` exposes the single-user view and keeps `user_id` internal.

Seeding happens only on a genuinely fresh database (detected by an empty `user_profile`).
A user who clears their watchlist keeps it cleared across restarts — do not re-seed a table
just because it happens to be empty. Default tickers come from
`app/market/seed_prices.py`, which is the single source of truth for the ticker list.

### Service layer — `backend/app/services/`

```python
from app.services import portfolio, watchlist_service

portfolio.get_portfolio(conn, cache)
# -> {"cash_balance", "positions": [...], "total_value", "total_unrealized_pnl"}
# each position: ticker, quantity, avg_cost, current_price, position_value,
#                unrealized_pnl, pnl_pct

await portfolio.execute_trade(conn, cache, source, ticker, side, quantity)
# ASYNC. -> dict describing the fill; raises TradeError(message) on any rejection.
# Reads fill price from the cache, auto-adds unpriced tickers to the watchlist,
# rejects unknown symbols, writes trades + positions + cash + a snapshot.

portfolio.record_snapshot(conn, cache)   # -> dict

watchlist_service.list_with_prices(conn, cache)
await watchlist_service.add_ticker(conn, cache, source, ticker)     # ASYNC, TradeError on bad symbol
await watchlist_service.remove_ticker(conn, cache, source, ticker)  # ASYNC
```

`execute_trade`, `add_ticker` and `remove_ticker` are **async** — they may have to ask the
market source to start pricing a symbol before the price exists. The read-only calls
(`get_portfolio`, `list_with_prices`, `list_history`, `record_snapshot`) stay synchronous.
Parameter order is otherwise exactly as frozen.

`TradeError` lives in `app/services/errors.py` and is the single rejection type the API and
the LLM auto-executor both catch.

### HTTP API

PLAN.md §8 is the contract, exactly as written. The frontend and the E2E suite code against
it. Any deviation is a bug in the backend, not in the consumers.

## Definition of done

- Your unit tests pass, and the whole backend suite stays green.
- `cd backend && uv run --extra dev ruff check app/ tests/` is clean for your files.
- Frontend: `npm run lint`, `npm test`, and `npm run build` all succeed and the build emits
  a static export.
- You reported what you built, what you verified, and anything you deliberately left out.
