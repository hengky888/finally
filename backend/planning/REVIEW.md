# Change Review

## Findings

### [P1] Install the optional `dev` extra in the quick start

`README.md:34-37` tells a fresh checkout to run `uv sync --dev` and then `uv run pytest`, but `backend/pyproject.toml:15-16` declares `dev` under `[project.optional-dependencies]`, not as a dependency group. In uv, `--dev` selects the development dependency group; it does not select an optional extra named `dev`. On a clean environment pytest is therefore not installed and the advertised quick start fails. Change the setup command to `uv sync --extra dev` (or move these dependencies into `[dependency-groups].dev`).

### [P1] Make the SSE cadence match the completed implementation

`planning/PLAN.md:180-182` now says the server re-emits every priced ticker every ~500 ms and that Massive-mode intervals between polls produce `"flat"` events. The completed stream does not do that: `backend/app/market/stream.py:64-85` yields only when `PriceCache.version` changes, while `backend/app/market/massive_client.py:86` does not update the cache between its 2-15 second polls. Consequently, Massive mode produces no 500 ms events between polls. This is a shared frontend/backend contract, so either remove the stream's version gate and deliberately emit snapshots every 500 ms, or document the actual update-on-cache-change behavior before the frontend is built around the wrong cadence.

### [P1] Define how an unpriced Massive ticker obtains a fill price

`planning/PLAN.md:281-284` requires an unpriced ticker to be auto-added and the trade to fill from the cache at execution time. In Massive mode, however, `MassiveDataSource.add_ticker()` only appends the ticker and explicitly waits for the next poll (`backend/app/market/massive_client.py:66-70`); it does not populate the cache. A trade request therefore has no price with which to validate or execute for as long as 15 seconds. Specify and implement one concrete behavior—an immediate single-symbol fetch/poll with a timeout, a queued trade, or a rejection requiring retry—and state whether the automatic watchlist addition is rolled back when pricing fails.

### [P2] Preserve the repository's enabled plugins when adding the hook

`.claude/settings.json:1-14` replaces the entire previous `enabledPlugins` block with the new `hooks` block. This removes the repository-level enablement for `frontend-design`, `context7`, and `playwright`, so a fresh collaborator will no longer get the tools the project had explicitly configured for frontend and E2E work. Merge the new `hooks` key alongside the existing `enabledPlugins` key rather than replacing it.

### [P2] Add source-independent symbol validation

`planning/PLAN.md:283` promises that unrecognized symbols are rejected, but the default simulator recognizes every string: `backend/app/market/simulator.py:151-152` gives unknown tickers a random seed price and default parameters. Inputs such as `NOT_A_STOCK` would therefore be priced and traded in the default product path. Define the supported ticker universe or add a validation service before either data source is mutated, so simulator and Massive modes enforce the same API contract.

### [P2] Do not commit a blanket local approval for arbitrary Codex runs

`.claude/settings.local.json:4` auto-approves every command matching `codex exec *`, not only the fixed review commands introduced in `.claude/settings.json` and `.claude/agents/change-reviewer.md`. The file is also not ignored, so it currently appears as a committable untracked change. If shared, any Claude workflow could launch a write-capable Codex prompt without another approval. Keep `settings.local.json` ignored/local, or narrow the permission to the exact intended command if shared approval is truly required.

## Validation

- `git diff --check HEAD` passed.
- `backend/.venv/Scripts/python.exe -m pytest -q` passed: 73 tests.
- The tests emitted 73 existing `asyncio.DefaultEventLoopPolicy` deprecation warnings.
