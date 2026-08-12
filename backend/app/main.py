"""FastAPI application for the FinAlly backend.

Owns process-wide setup that the market data package deliberately does not:
reading `.env`, configuring logging, and running the market data source for the
lifetime of the app. See PLAN.md section 10.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request

from app.market import (
    MarketDataSource,
    PriceCache,
    create_market_data_source,
    create_stream_router,
)
from app.market.seed_prices import DEFAULT_WATCHLIST

logger = logging.getLogger(__name__)

# backend/app/main.py -> backend/app -> backend -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def configure_logging() -> None:
    """Attach a handler so the subsystem's log calls are actually visible.

    Without this the root logger has no INFO handler under a stock uvicorn
    launch and every logger.info() in app.market is silently discarded.
    """
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        force=True,  # Override uvicorn's own basicConfig if it got there first
    )


def load_initial_tickers() -> list[str]:
    """The tickers to price at startup.

    Currently the static seed list. When the database lands this becomes the
    union of the watchlist and all open positions (PLAN.md section 6) — the
    market data layer needs no change, only this function.
    """
    return list(DEFAULT_WATCHLIST)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start and stop the market data feed alongside the app.

    `.env` is loaded here rather than at import time so the factory sees the
    same environment the running app does.
    """
    load_dotenv(PROJECT_ROOT / ".env")
    configure_logging()

    price_cache: PriceCache = app.state.price_cache
    source = create_market_data_source(price_cache)
    app.state.market_source = source

    await source.start(load_initial_tickers())
    logger.info("FinAlly backend ready: %d tickers priced", len(price_cache.get_all()))

    try:
        yield
    finally:
        # In a finally block so a crash during serving still shuts the feed down
        # cleanly instead of leaking the background task.
        await source.stop()
        app.state.market_source = None


def create_app() -> FastAPI:
    """Build the application. A factory so tests can construct isolated apps."""
    app = FastAPI(title="FinAlly", version="0.1.0", lifespan=lifespan)

    # Built eagerly: it is a plain in-memory object with no I/O, and the SSE
    # router needs to close over it at registration time. Only the data *source*
    # has a lifecycle, so only that lives in lifespan.
    price_cache = PriceCache()
    app.state.price_cache = price_cache
    app.state.market_source = None

    @app.get("/api/health", tags=["system"])
    async def health() -> dict:
        """Liveness/readiness probe for Docker and deployment platforms.

        Reports `priced_tickers` so a deploy check can distinguish "process up"
        from "market data actually flowing".
        """
        return {"status": "ok", "priced_tickers": len(price_cache.get_all())}

    app.include_router(create_stream_router(price_cache))
    return app


# --- Dependency accessors for downstream routers (portfolio, watchlist, chat) ---


def get_price_cache(request: Request) -> PriceCache:
    """FastAPI dependency: the shared price cache."""
    return request.app.state.price_cache


def get_market_source(request: Request) -> MarketDataSource:
    """FastAPI dependency: the running market data source."""
    return request.app.state.market_source


app = create_app()
