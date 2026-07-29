"""Abstract interface for market data sources."""

from __future__ import annotations

from abc import ABC, abstractmethod


class UnknownSymbolError(Exception):
    """The symbol is not tradeable by this source. Permanent — do not retry.

    Maps to HTTP 400.
    """


class PricingUnavailableError(Exception):
    """The symbol may be valid but no price could be obtained right now.

    Transient (API timeout, rate limit, network). Maps to HTTP 503.
    """


class MarketDataSource(ABC):
    """Contract for market data providers.

    Implementations push price updates into a shared PriceCache on their own
    schedule. Downstream code never calls the data source directly for prices —
    it reads from the cache.

    Lifecycle:
        source = create_market_data_source(cache)
        await source.start(["AAPL", "GOOGL", ...])
        # ... app runs ...
        await source.add_ticker("TSLA")
        price = await source.ensure_priced("PYPL")   # blocking, for trades
        await source.remove_ticker("GOOGL")
        # ... app shutting down ...
        await source.stop()
    """

    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Begin producing price updates for the given tickers.

        Starts a background task that periodically writes to the PriceCache.
        Must be called exactly once. Calling start() twice is undefined behavior.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Stop the background task and release resources.

        Safe to call multiple times. After stop(), the source will not write
        to the cache again.
        """

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Add a ticker to the active set. No-op if already present.

        Fire-and-forget: does NOT guarantee a price exists on return.
        Use ensure_priced() when a price is required immediately.
        """

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker from the active set. No-op if not present.

        Also removes the ticker from the PriceCache.
        """

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Return the current list of actively tracked tickers."""

    @abstractmethod
    async def ensure_priced(self, ticker: str, timeout: float = 5.0) -> float:
        """Guarantee the cache holds a price for `ticker`, and return it.

        Adds the ticker to the active set as a side effect *only on success*.
        Blocks until a price is available or `timeout` elapses.

        Raises:
            UnknownSymbolError: the source cannot price this symbol (permanent).
            PricingUnavailableError: no price obtainable right now (transient).
        """
