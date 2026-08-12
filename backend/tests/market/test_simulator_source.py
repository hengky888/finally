"""Integration tests for SimulatorDataSource."""

import asyncio

import pytest

from app.market.cache import PriceCache
from app.market.interface import PricingUnavailableError, UnknownSymbolError
from app.market.simulator import GBMSimulator, SimulatorDataSource
from app.market.symbols import InvalidSymbolFormatError


@pytest.mark.asyncio
class TestSimulatorDataSource:
    """Integration tests for the SimulatorDataSource."""

    async def test_start_populates_cache(self):
        """Test that start() immediately populates the cache."""
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=0.1)
        await source.start(["AAPL", "GOOGL"])

        # Cache should have seed prices immediately (before first loop tick)
        assert cache.get("AAPL") is not None
        assert cache.get("GOOGL") is not None

        await source.stop()

    async def test_prices_update_over_time(self):
        """Test that prices are updated periodically."""
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=0.05)
        await source.start(["AAPL"])

        initial_version = cache.version
        await asyncio.sleep(0.3)  # Several update cycles

        # Version should have incremented (prices updated)
        assert cache.version > initial_version

        await source.stop()

    async def test_stop_is_clean(self):
        """Test that stop() is clean and idempotent."""
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=0.1)
        await source.start(["AAPL"])
        await source.stop()
        # Double stop should not raise
        await source.stop()

    async def test_add_ticker(self):
        """Test adding a ticker dynamically."""
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=0.1)
        await source.start(["AAPL"])

        await source.add_ticker("TSLA")
        assert "TSLA" in source.get_tickers()
        assert cache.get("TSLA") is not None

        await source.stop()

    async def test_remove_ticker(self):
        """Test removing a ticker."""
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=0.1)
        await source.start(["AAPL", "TSLA"])

        await source.remove_ticker("TSLA")
        assert "TSLA" not in source.get_tickers()
        assert cache.get("TSLA") is None

        await source.stop()

    async def test_get_tickers(self):
        """Test getting the list of active tickers."""
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=0.1)
        await source.start(["AAPL", "GOOGL"])

        tickers = source.get_tickers()
        assert set(tickers) == {"AAPL", "GOOGL"}

        await source.stop()

    async def test_empty_start(self):
        """Test starting with no tickers."""
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=0.1)
        await source.start([])

        assert len(cache) == 0
        assert source.get_tickers() == []

        await source.stop()

    async def test_exception_resilience(self):
        """Test that simulator continues running after errors."""
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=0.05)

        # Start with a valid ticker
        await source.start(["AAPL"])

        # Wait for some updates
        await asyncio.sleep(0.15)

        # Task should still be running
        assert source._task is not None
        assert not source._task.done()

        await source.stop()

    async def test_custom_update_interval(self):
        """Test using a custom update interval."""
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=0.01)
        await source.start(["AAPL"])

        initial_version = cache.version
        await asyncio.sleep(0.05)  # Should get ~5 updates

        # Should have multiple updates with fast interval
        assert cache.version > initial_version + 2

        await source.stop()

    async def test_custom_event_probability(self):
        """Test creating source with custom event probability."""
        cache = PriceCache()
        # Very high event probability for testing
        source = SimulatorDataSource(price_cache=cache, update_interval=0.1, event_probability=1.0)
        await source.start(["AAPL"])

        # Just verify it starts and stops cleanly
        await asyncio.sleep(0.2)
        await source.stop()

    async def test_ensure_priced_returns_cached_price(self):
        """A ticker already in the cache is returned without any side effects."""
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=0.1)
        await source.start(["AAPL"])

        price = await source.ensure_priced("AAPL")
        assert price == cache.get_price("AAPL")

        await source.stop()

    async def test_ensure_priced_adds_unwatched_symbol(self):
        """A valid symbol outside the active set is seeded and added on success."""
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=0.1)
        await source.start([])

        price = await source.ensure_priced("TSLA")

        assert price is not None
        assert "TSLA" in source.get_tickers()
        assert cache.get_price("TSLA") == price

        await source.stop()

    async def test_ensure_priced_normalizes_symbol(self):
        """Input is normalized (uppercased, trimmed) before validation."""
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=0.1)
        await source.start([])

        price = await source.ensure_priced("  aapl ")

        assert price is not None
        assert "AAPL" in source.get_tickers()

        await source.stop()

    async def test_ensure_priced_rejects_symbol_outside_universe(self):
        """A well-formed but unrecognized symbol is a permanent rejection."""
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=0.1)
        await source.start([])

        with pytest.raises(UnknownSymbolError):
            await source.ensure_priced("ZZZZ")

        assert "ZZZZ" not in source.get_tickers()

        await source.stop()

    async def test_ensure_priced_rejects_malformed_symbol(self):
        """A malformed symbol fails shape validation before the universe check."""
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=0.1)
        await source.start([])

        with pytest.raises(InvalidSymbolFormatError):
            await source.ensure_priced("123")

        await source.stop()


@pytest.mark.asyncio
class TestUniverseEnforcement:
    """add_ticker and ensure_priced must agree; the watchlist path reaches add_ticker."""

    async def test_add_ticker_rejects_symbol_outside_universe(self):
        """A well-formed but untraded symbol must not get an invented price."""
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=10)
        await source.start(["AAPL"])

        with pytest.raises(UnknownSymbolError):
            await source.add_ticker("ZZZZZ")

        assert "ZZZZZ" not in source.get_tickers()
        assert cache.get_price("ZZZZZ") is None
        await source.stop()

    async def test_add_ticker_rejects_malformed_symbol(self):
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=10)
        await source.start(["AAPL"])
        with pytest.raises(InvalidSymbolFormatError):
            await source.add_ticker("not a ticker!")
        await source.stop()

    async def test_add_ticker_accepts_universe_symbol(self):
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=10)
        await source.start(["AAPL"])
        await source.add_ticker("amd")  # lowercase, in universe, unseeded
        assert "AMD" in source.get_tickers()
        assert cache.get_price("AMD") is not None
        await source.stop()

    async def test_add_before_start_is_explicit_not_silent(self):
        """Previously a no-op that looked like success."""
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache)
        with pytest.raises(PricingUnavailableError):
            await source.add_ticker("AAPL")

    async def test_start_skips_unpriceable_tickers_instead_of_crashing(self):
        """A watchlist holding a stale symbol must not stop the app booting."""
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=10)
        await source.start(["AAPL", "ZZZZZ", "not a ticker!", "googl"])
        assert set(source.get_tickers()) == {"AAPL", "GOOGL"}
        await source.stop()


@pytest.mark.asyncio
class TestTimeStepScaling:
    """dt must track update_interval or volatility mis-scales with the tick rate."""

    async def test_dt_derived_from_update_interval(self):
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=0.05)
        await source.start(["AAPL"])
        expected = 0.05 / GBMSimulator.TRADING_SECONDS_PER_YEAR
        assert source._sim._dt == pytest.approx(expected)
        await source.stop()

    async def test_default_interval_matches_the_documented_default(self):
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache)
        await source.start(["AAPL"])
        assert source._sim._dt == pytest.approx(GBMSimulator.DEFAULT_DT)
        await source.stop()

    async def test_halving_the_interval_halves_dt(self):
        cache = PriceCache()
        fast = SimulatorDataSource(price_cache=cache, update_interval=0.25)
        slow = SimulatorDataSource(price_cache=PriceCache(), update_interval=0.5)
        await fast.start(["AAPL"])
        await slow.start(["AAPL"])
        assert slow._sim._dt == pytest.approx(fast._sim._dt * 2)
        await fast.stop()
        await slow.stop()


@pytest.mark.asyncio
class TestDeterminism:
    """A seed makes a run reproducible, which E2E tests need."""

    async def test_same_seed_produces_same_prices(self):
        results = []
        for _ in range(2):
            cache = PriceCache()
            source = SimulatorDataSource(price_cache=cache, update_interval=10, seed=1234)
            await source.start(["AAPL", "GOOGL"])
            source._sim.step()
            results.append(source._sim.step())
            await source.stop()
        assert results[0] == results[1]

    async def test_different_seeds_diverge(self):
        prices = []
        for seed in (1, 2):
            cache = PriceCache()
            source = SimulatorDataSource(price_cache=cache, update_interval=10, seed=seed)
            await source.start(["AAPL"])
            for _ in range(50):
                source._sim.step()
            prices.append(source._sim.get_price("AAPL"))
            await source.stop()
        assert prices[0] != prices[1]


@pytest.mark.asyncio
class TestSimulatorDailyChange:
    async def test_reference_is_the_session_open(self):
        cache = PriceCache()
        source = SimulatorDataSource(price_cache=cache, update_interval=10)
        await source.start(["AAPL"])
        update = cache.get("AAPL")
        assert update.reference_price == update.price
        assert update.daily_change_percent == 0.0
        await source.stop()
