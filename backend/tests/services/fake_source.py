"""A market data source that prices a fixed universe, with no background task."""

from __future__ import annotations

from app.market import MarketDataSource, PriceCache, UnknownSymbolError
from app.market.symbols import normalize_symbol

# The symbols tests may trade. PYPL is deliberately left out of the seeded
# cache so the auto-add-on-trade path can be exercised.
UNIVERSE = {"AAPL": 100.0, "MSFT": 200.0, "TSLA": 50.0, "PYPL": 25.0}


def seeded_cache(cache: PriceCache) -> PriceCache:
    """Fill a cache with the test universe, except PYPL."""
    for ticker, price in UNIVERSE.items():
        if ticker != "PYPL":
            cache.update(ticker, price)
    return cache


def seeded_source(cache: PriceCache) -> "FakeSource":
    """A fake source already tracking whatever the cache holds."""
    source = FakeSource(cache, dict(UNIVERSE))
    source.tickers = [t for t in UNIVERSE if cache.get_price(t) is not None]
    return source


class FakeSource(MarketDataSource):
    """Prices only the symbols it was given, instantly and deterministically."""

    def __init__(self, cache: PriceCache, universe: dict[str, float]) -> None:
        self.cache = cache
        self.universe = universe
        self.tickers: list[str] = []
        self.started = False
        self.stopped = False

    async def start(self, tickers: list[str]) -> None:
        self.started = True
        for ticker in tickers:
            await self.add_ticker(ticker)

    async def stop(self) -> None:
        self.stopped = True

    async def add_ticker(self, ticker: str) -> None:
        symbol = normalize_symbol(ticker)
        if symbol in self.universe and symbol not in self.tickers:
            self.tickers.append(symbol)
            self.cache.update(symbol, self.universe[symbol])

    async def remove_ticker(self, ticker: str) -> None:
        symbol = normalize_symbol(ticker)
        if symbol in self.tickers:
            self.tickers.remove(symbol)
        self.cache.remove(symbol)

    def get_tickers(self) -> list[str]:
        return list(self.tickers)

    async def ensure_priced(self, ticker: str, timeout: float = 5.0) -> float:
        symbol = normalize_symbol(ticker)
        if symbol not in self.universe:
            raise UnknownSymbolError(f"{symbol} is not tradeable here")
        await self.add_ticker(symbol)
        return self.cache.get_price(symbol)
