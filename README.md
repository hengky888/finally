# FinAlly — AI Trading Workstation

An AI-powered trading workstation that streams live market data, simulates portfolio trading, and integrates an LLM chat assistant that can analyze positions and execute trades from natural language.

Built entirely by coding agents as the capstone project for an agentic AI coding course.

## Status

All components are built and green: market data, database, portfolio and watchlist services, the HTTP API, LLM chat, the Next.js frontend, Docker packaging, and the E2E suite. 283 backend tests, 125 frontend tests, 11 Playwright scenarios.

See [planning/PLAN.md](planning/PLAN.md) for the full specification and [planning/market_data_summary.md](planning/market_data_summary.md) for the market data subsystem.

## Features

- Live price streaming over SSE with green/red flash animations
- Simulated portfolio — $10k virtual cash, market orders, instant fills
- Portfolio visualizations — heatmap, P&L chart, positions table
- AI chat assistant that suggests and auto-executes trades
- Watchlist management, manual or via chat
- Dark, data-dense terminal aesthetic

## Architecture

A single Docker container serving everything on port 8000:

- **Frontend**: Next.js static export, TypeScript, Tailwind CSS
- **Backend**: FastAPI (Python, managed with `uv`) with SSE streaming
- **Database**: SQLite, seeded on startup
- **AI**: LiteLLM to OpenRouter (Cerebras inference) with structured outputs
- **Market data**: built-in GBM simulator by default, Massive API when a key is set

## Running the App

```bash
./scripts/start_mac.sh           # macOS/Linux; add --build to force a rebuild
./scripts/stop_mac.sh
```

```powershell
.\scripts\start_windows.ps1      # Windows; add -Build to force a rebuild
.\scripts\stop_windows.ps1
```

Then open http://localhost:8000. The SQLite database lives on the `finally-data`
volume and survives stop/start; the stop scripts never remove it.

## Running the Backend

```bash
cd backend
uv sync --extra dev
uv run market_data_demo.py       # live terminal price dashboard
uv run --extra dev pytest        # test suite
```

## Running the Tests

```bash
cd backend && uv run --extra dev pytest      # 283 backend tests
cd frontend && npm test                      # 125 frontend tests
```

E2E: see [test/README.md](test/README.md).

## Environment Variables

Create a `.env` in the project root:

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | For chat only | OpenRouter key; the server boots and streams prices without it |
| `MASSIVE_API_KEY` | No | Massive (Polygon.io) key for real market data; omit to use the simulator |
| `LLM_MOCK` | No | Set `true` for deterministic mock LLM responses in tests |

## Project Structure

```
finally/
├── backend/     # FastAPI uv project
├── frontend/    # Next.js static export
├── planning/    # Specification and agent contracts
├── test/        # Playwright E2E tests
├── db/          # SQLite volume mount (runtime)
└── scripts/     # Start/stop helpers
```

## License

See [LICENSE](LICENSE).
