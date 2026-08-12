"""Massive (Polygon.io) API client for real market data."""

from __future__ import annotations

import asyncio
import logging

from massive import RESTClient
from massive.rest.models import SnapshotMarketType

from .cache import PriceCache
from .interface import MarketDataSource, PricingUnavailableError, UnknownSymbolError
from .symbols import normalize_symbol

logger = logging.getLogger(__name__)

_MAX_CONSECUTIVE_FAILURES_BEFORE_ESCALATION = 3


class MassiveDataSource(MarketDataSource):
    """MarketDataSource backed by the Massive (Polygon.io) REST API.

    Polls GET /v2/snapshot/locale/us/markets/stocks/tickers for all watched
    tickers in a single API call, then writes results to the PriceCache.

    Rate limits:
      - Free tier: 5 req/min → poll every 15s (default)
      - Paid tiers: higher limits → poll every 2-5s
    """

    def __init__(
        self,
        api_key: str,
        price_cache: PriceCache,
        poll_interval: float = 15.0,
    ) -> None:
        self._api_key = api_key
        self._cache = price_cache
        self._interval = poll_interval
        self._tickers: list[str] = []
        self._task: asyncio.Task | None = None
        self._client: RESTClient | None = None
        self._consecutive_failures: int = 0

    async def start(self, tickers: list[str]) -> None:
        self._client = RESTClient(api_key=self._api_key)
        self._tickers = list(tickers)

        # Do an immediate first poll so the cache has data right away
        await self._poll_once()

        self._task = asyncio.create_task(self._poll_loop(), name="massive-poller")
        logger.info(
            "Massive poller started: %d tickers, %.1fs interval",
            len(tickers),
            self._interval,
        )

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._client = None
        logger.info("Massive poller stopped")

    async def add_ticker(self, ticker: str) -> None:
        symbol = normalize_symbol(ticker)
        if symbol not in self._tickers:
            self._tickers.append(symbol)
            logger.info("Massive: added %s (appears on next poll)", symbol)

    async def remove_ticker(self, ticker: str) -> None:
        symbol = normalize_symbol(ticker)
        self._tickers = [t for t in self._tickers if t != symbol]
        self._cache.remove(symbol)
        logger.info("Massive: removed ticker %s", symbol)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    async def ensure_priced(self, ticker: str, timeout: float = 5.0) -> float:
        """Fetch a single symbol on demand rather than waiting for the next poll.

        Only joins the polled set *after* a price is confirmed, so a failed
        lookup leaves no residue to roll back.
        """
        symbol = normalize_symbol(ticker)

        cached = self._cache.get_price(symbol)
        if cached is not None and symbol in self._tickers:
            return cached

        if self._client is None:
            raise PricingUnavailableError("Market data source is not running")

        try:
            snapshot = await asyncio.wait_for(
                asyncio.to_thread(self._fetch_one, symbol), timeout=timeout
            )
        except TimeoutError as exc:
            raise PricingUnavailableError(f"Timed out fetching a price for {symbol}") from exc
        except Exception as exc:
            # 404 / empty result = unknown symbol; anything else is transient.
            if _is_not_found(exc):
                raise UnknownSymbolError(f"{symbol} is not a recognized symbol") from exc
            raise PricingUnavailableError(
                f"Could not fetch a price for {symbol}: {exc}"
            ) from exc

        price = getattr(getattr(snapshot, "last_trade", None), "price", None)
        if price is None:
            raise UnknownSymbolError(f"No trade data available for {symbol}")

        timestamp = snapshot.last_trade.timestamp / 1000.0
        self._cache.update(ticker=symbol, price=price, timestamp=timestamp)

        # Success — now (and only now) join the polled set.
        if symbol not in self._tickers:
            self._tickers.append(symbol)

        return round(price, 2)

    # --- Internal ---

    async def _poll_loop(self) -> None:
        """Poll on interval. First poll already happened in start()."""
        while True:
            await asyncio.sleep(self._interval)
            await self._poll_once()

    async def _poll_once(self) -> None:
        """Execute one poll cycle: fetch snapshots, update cache."""
        if not self._tickers or not self._client:
            return

        try:
            # The Massive RESTClient is synchronous — run in a thread to
            # avoid blocking the event loop.
            snapshots = await asyncio.to_thread(self._fetch_snapshots)
            processed = 0
            for snap in snapshots:
                try:
                    price = snap.last_trade.price
                    # Massive timestamps are Unix milliseconds → convert to seconds
                    timestamp = snap.last_trade.timestamp / 1000.0
                    self._cache.update(
                        ticker=snap.ticker,
                        price=price,
                        timestamp=timestamp,
                    )
                    processed += 1
                except (AttributeError, TypeError) as e:
                    logger.warning(
                        "Skipping snapshot for %s: %s",
                        getattr(snap, "ticker", "???"),
                        e,
                    )
            logger.debug("Massive poll: updated %d/%d tickers", processed, len(self._tickers))
            self._consecutive_failures = 0

        except Exception as e:
            # Don't re-raise — the loop will retry on the next interval.
            # Common failures: 401 (bad key), 429 (rate limit), network errors.
            self._consecutive_failures += 1
            if self._consecutive_failures >= _MAX_CONSECUTIVE_FAILURES_BEFORE_ESCALATION:
                logger.error(
                    "Massive poll failed %d times in a row (possible bad API key "
                    "or persistent network issue): %s",
                    self._consecutive_failures,
                    e,
                )
            else:
                logger.error("Massive poll failed: %s", e)

    def _fetch_snapshots(self) -> list:
        """Synchronous call to the Massive REST API. Runs in a thread."""
        return self._client.get_snapshot_all(
            market_type=SnapshotMarketType.STOCKS,
            tickers=self._tickers,
        )

    def _fetch_one(self, symbol: str):
        """Synchronous single-ticker call. Runs in a worker thread."""
        return self._client.get_snapshot_ticker(
            market_type=SnapshotMarketType.STOCKS,
            ticker=symbol,
        )


def _is_not_found(exc: Exception) -> bool:
    """Best-effort classification of 'symbol does not exist' vs. transient failure."""
    status = getattr(exc, "status", None) or getattr(exc, "status_code", None)
    if status in (400, 404):
        return True
    return "not found" in str(exc).lower()
