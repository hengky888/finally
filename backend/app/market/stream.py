"""SSE streaming endpoint for live price updates."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache
from .models import PriceUpdate

logger = logging.getLogger(__name__)


def create_stream_router(price_cache: PriceCache, interval: float = 0.5) -> APIRouter:
    """Build the SSE router bound to a PriceCache.

    A fresh APIRouter per call so the route can't be registered twice when
    tests build more than one app.
    """
    router = APIRouter(prefix="/api/stream", tags=["streaming"])

    @router.get("/prices")
    async def stream_prices(request: Request) -> StreamingResponse:
        """Live price stream. Connect with `new EventSource('/api/stream/prices')`.

        Emits every priced ticker each tick — including unchanged ones
        (`direction: "flat"`) — so the client can distinguish a quiet market
        from a dead connection. `direction` is computed per connection,
        relative to the last price that connection was sent.
        """
        return StreamingResponse(
            _generate_events(price_cache, request, interval),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                # No "Connection" header: it is hop-by-hop, already the default
                # under HTTP/1.1, and illegal under HTTP/2.
                "X-Accel-Buffering": "no",  # Disable nginx buffering if proxied
            },
        )

    return router


def _diff(ticker: str, update: PriceUpdate, last: float | None) -> dict:
    """Build one ticker's payload relative to the last price THIS connection sent.

    `change`/`direction` are per-connection so every client gets a correct flash
    regardless of when it connected. `daily_*` come from the cache's session
    reference and are identical for all clients.
    """
    price = update.price
    previous = price if last is None else last
    change = round(price - previous, 4)
    if change > 0:
        direction = "up"
    elif change < 0:
        direction = "down"
    else:
        direction = "flat"
    return {
        "ticker": ticker,
        "price": price,
        "previous_price": previous,
        "change": change,
        "change_percent": round(change / previous * 100, 4) if previous else 0.0,
        "direction": direction,
        "timestamp": update.timestamp,
        "reference_price": update.reference_price,
        "daily_change": update.daily_change,
        "daily_change_percent": update.daily_change_percent,
    }


async def _generate_events(
    price_cache: PriceCache,
    request: Request,
    interval: float = 0.5,
) -> AsyncGenerator[str, None]:
    """Yield an SSE event every `interval` seconds for every priced ticker.

    Emits unconditionally — unchanged tickers are reported as 'flat'. This keeps
    the stream alive between Massive polls and lets the client treat silence as
    a genuine connection problem.
    """
    yield "retry: 1000\n\n"

    client_ip = request.client.host if request.client else "unknown"
    logger.info("SSE client connected: %s", client_ip)

    last_sent: dict[str, float] = {}
    seq = 0

    try:
        while True:
            if await request.is_disconnected():
                logger.info("SSE client disconnected: %s", client_ip)
                break

            snapshot = price_cache.get_all()
            prices = {
                ticker: _diff(ticker, u, last_sent.get(ticker)) for ticker, u in snapshot.items()
            }
            # Forget tickers that left the priced set, so a re-add starts flat.
            last_sent = {ticker: u.price for ticker, u in snapshot.items()}

            # Emit unconditionally, including `prices: {}` for an empty watchlist.
            # Skipping empty ticks would make a healthy connection indistinguishable
            # from a dead one in exactly the case where the user has no tickers.
            seq += 1
            payload = json.dumps({"seq": seq, "ts": time.time(), "prices": prices})
            yield f"data: {payload}\n\n"

            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("SSE stream cancelled for: %s", client_ip)
        raise
