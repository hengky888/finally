# FinAlly — AI Trading Workstation

An AI-powered trading workstation that streams live market data, simulates portfolio trading, and integrates an LLM chat assistant that can analyze positions and execute trades from natural language.

Built entirely by coding agents as the capstone project for an agentic AI coding course.

## Status

The market data subsystem is complete (GBM simulator, Massive/Polygon.io client, price cache, SSE endpoint — 73 tests passing). Portfolio, LLM chat, frontend, and Docker packaging are still to be built.

See [planning/PLAN.md](planning/PLAN.md) for the full specification and [planning/market_data_summary.md](planning/market_data_summary.md) for what exists today.

## Planned Features

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

## Running the Backend

```bash
cd backend
uv sync --extra dev
uv run market_data_demo.py       # live terminal price dashboard
uv run --extra dev pytest        # test suite
```

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
├── backend/     # FastAPI uv project (market data complete)
├── frontend/    # Next.js static export (planned)
├── planning/    # Specification and agent contracts
├── test/        # Playwright E2E tests (planned)
├── db/          # SQLite volume mount (runtime)
└── scripts/     # Start/stop helpers (planned)
```

## License

See [LICENSE](LICENSE).
