# Change Review

## Findings

### [P1] Run only one Stop hook

`.claude/settings.json:2-13` registers a repository-level `Stop` hook, while `independent-reviewer/hooks/hooks.json:2-13` registers the same hook through the plugin enabled at `.claude/settings.json:14-16`. When that plugin is available, a single Claude stop launches two `codex exec` processes. Both processes review the same tree and write `planning/REVIEW.md`, so they waste a full review run and can race while overwriting the same file. Keep the hook in either the plugin or the repository settings, not both.

### [P1] Anchor review runs to the repository root

All three review entry points use a relative output path: `.claude/settings.json:8`, `independent-reviewer/hooks/hooks.json:8`, and `.claude/agents/change-reviewer.md:8`. `codex exec` inherits the session's current working directory, so a Claude session started in `backend/` writes `backend/planning/REVIEW.md` rather than the required root-level file. That failure has already occurred: the working tree contains an untracked `backend/planning/REVIEW.md`. Invoke Codex with its working directory explicitly set to the Claude project root (for example, via `codex exec -C <project-root> ...`) and make the requested destination unambiguous.

### [P1] Make the documented SSE cadence match the completed stream

`planning/PLAN.md:180-182` now promises a snapshot every ~500 ms and says unchanged Massive prices are re-emitted as `"flat"` events between polls. The completed generator only yields when `PriceCache.version` changes (`backend/app/market/stream.py:64-85`), while the Massive source does not touch the cache between its 2-15 second polls (`backend/app/market/massive_client.py:83-87`). Massive mode therefore emits no events between polls. Because the README calls this subsystem complete and the plan is the frontend contract, either remove the version gate and deliberately emit every 500 ms or document the actual update-on-cache-change behavior.

### [P1] Define how an unpriced Massive ticker gets a fill price

`planning/PLAN.md:281-285` says a trade in an unpriced ticker is auto-added and fills from the cache at execution time. In Massive mode, `add_ticker()` only adds the symbol to a list and waits for the next poll (`backend/app/market/massive_client.py:66-70`), which can take 15 seconds; there is no price available for immediate validation or execution. Specify one implementable behavior before the portfolio code is built: fetch the symbol immediately with a timeout, queue the trade, or reject it and require a retry. Also define whether the automatic watchlist addition is rolled back if pricing fails.

### [P2] Register the local marketplace in project settings

`.claude/settings.json:14-16` enables `independent-reviewer@heng-tools`, but it does not declare `heng-tools` under `extraKnownMarketplaces`. The plugin works on this machine only because the marketplace has already been registered in user state; committing `.claude-plugin/marketplace.json` by itself does not register it for a fresh clone. Add the local directory marketplace to project settings (or document a required installation step) so collaborators can resolve the enabled plugin. Anthropic's [marketplace documentation](https://code.claude.com/docs/en/plugin-marketplaces#require-marketplaces-for-your-team) describes `extraKnownMarketplaces` as the repository-level mechanism.

### [P2] Preserve the repository's existing project plugins

The `enabledPlugins` edit in `.claude/settings.json:14-16` removes `frontend-design`, `context7`, and `playwright` instead of adding the reviewer alongside them. That changes a fresh collaborator's project toolset and removes the frontend and E2E plugins just before those parts of the project are scheduled to be built. Restore the existing entries unless their removal is an explicit part of this change.

### [P2] Add source-independent ticker validation

`planning/PLAN.md:283` says unrecognized symbols are rejected, but the default simulator accepts every non-empty string by assigning an unknown symbol a random seed price and default parameters (`backend/app/market/simulator.py:146-152`). As written, `NOT_A_STOCK` can be priced and traded in the default product mode even though Massive mode may reject it. Define a supported symbol universe or add a validation layer before either source or the watchlist is mutated.

### [P2] Do not commit blanket approval for arbitrary Codex prompts

`.claude/settings.local.json:1-7` is untracked but not ignored, so it can be committed with this change. Its `Bash(codex exec *)` rule approves every Codex prompt, not only the fixed review command. The plugin hook itself does not need a model-issued Bash approval, and the project agent can use a narrowly matched command if approval is required. Keep this file local/ignored or restrict the rule to the exact intended invocation.

### [P3] Remove the duplicate manifest key

`independent-reviewer/.claude-plugin/plugin.json:3-5` declares `"version"` twice. Claude's validator currently accepts it because both values are identical, but duplicate JSON object keys have parser-dependent behavior and make future version edits easy to apply to only one occurrence. Keep a single `version` field.

### [P3] Rename the stale database initialization heading

`planning/PLAN.md:189` still says "SQLite with Lazy Initialization", immediately before the newly changed text at line 191 says initialization is explicitly not lazy. Rename the heading to match the startup initialization contract.

## Validation

- `git diff --check HEAD` passed.
- `backend/.venv/Scripts/python.exe -m pytest -q backend/tests` passed: 73 tests.
- The tests emitted 73 existing `asyncio.DefaultEventLoopPolicy` deprecation warnings.
- `claude plugin validate .` and `claude plugin validate independent-reviewer` both passed with metadata warnings.
- `claude plugin details independent-reviewer@heng-tools` confirmed that the enabled plugin contributes one `Stop` hook in addition to the repository-level hook.
