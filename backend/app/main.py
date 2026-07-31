"""FastAPI application: lifespan, routes and static frontend serving."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import health_router, portfolio_router, watchlist_router
from app.config import Settings, get_settings
from app.db import get_connection, init_db
from app.llm import chat_router
from app.market import PriceCache, create_market_data_source, create_stream_router
from app.services import TradeError, portfolio

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database, then start the market and snapshot tasks."""
    settings: Settings = app.state.settings
    init_db(settings.db_path)
    logger.info("Database ready at %s", settings.db_path)

    conn = get_connection()
    try:
        tickers = portfolio.priced_tickers(conn)
    finally:
        conn.close()

    source = create_market_data_source(app.state.price_cache)
    await source.start(tickers)
    app.state.market_source = source

    app.state.snapshot_task = asyncio.create_task(
        _snapshot_loop(app.state.price_cache, settings.snapshot_interval),
        name="portfolio-snapshots",
    )
    logger.info("Started market data for %d tickers", len(tickers))

    yield

    app.state.snapshot_task.cancel()
    try:
        await app.state.snapshot_task
    except asyncio.CancelledError:
        pass
    await source.stop()
    logger.info("Background tasks stopped")


async def _snapshot_loop(cache: PriceCache, interval: float) -> None:
    """Record the portfolio's total value every `interval` seconds."""
    while True:
        await asyncio.sleep(interval)
        conn = get_connection()
        try:
            portfolio.record_snapshot(conn, cache)
        except Exception:
            logger.exception("Snapshot failed")
        finally:
            conn.close()


async def trade_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render a rejection as a 400 the UI can display verbatim."""
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def create_app() -> FastAPI:
    """Build the application with its routes and static file mount."""
    settings = get_settings()
    app = FastAPI(title="FinAlly", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.price_cache = PriceCache()

    app.add_exception_handler(TradeError, trade_error_handler)

    app.include_router(health_router)
    app.include_router(portfolio_router)
    app.include_router(watchlist_router)
    app.include_router(chat_router)
    app.include_router(create_stream_router(app.state.price_cache))

    # Static must be mounted last: it matches every path, so a router added
    # after it is unreachable once the frontend export is present.
    _mount_static(app, settings)
    return app


def _mount_static(app: FastAPI, settings: Settings) -> None:
    """Serve the frontend export at / when it is present.

    Mounted after the API routers, which are matched first. The frontend is
    built separately and is absent in development, which must not stop the
    server booting.
    """
    if not settings.static_dir.is_dir():
        logger.info("No static directory at %s; serving API only", settings.static_dir)
        return
    app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="static")
    logger.info("Serving frontend from %s", settings.static_dir)


app = create_app()
