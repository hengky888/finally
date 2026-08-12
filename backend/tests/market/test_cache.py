"""Tests for PriceCache."""

import threading

from app.market.cache import PriceCache


class TestPriceCache:
    """Unit tests for the PriceCache."""

    def test_update_and_get(self):
        """Test updating and getting a price."""
        cache = PriceCache()
        update = cache.update("AAPL", 190.50)
        assert update.ticker == "AAPL"
        assert update.price == 190.50
        assert cache.get("AAPL") == update

    def test_first_update_is_flat(self):
        """Test that the first update has flat direction."""
        cache = PriceCache()
        update = cache.update("AAPL", 190.50)
        assert update.direction == "flat"
        assert update.previous_price == 190.50

    def test_direction_up(self):
        """Test price update with upward direction."""
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        update = cache.update("AAPL", 191.00)
        assert update.direction == "up"
        assert update.change == 1.00

    def test_direction_down(self):
        """Test price update with downward direction."""
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        update = cache.update("AAPL", 189.00)
        assert update.direction == "down"
        assert update.change == -1.00

    def test_remove(self):
        """Test removing a ticker from cache."""
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        cache.remove("AAPL")
        assert cache.get("AAPL") is None

    def test_remove_nonexistent(self):
        """Test removing a ticker that doesn't exist."""
        cache = PriceCache()
        cache.remove("AAPL")  # Should not raise

    def test_get_all(self):
        """Test getting all prices."""
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        cache.update("GOOGL", 175.00)
        all_prices = cache.get_all()
        assert set(all_prices.keys()) == {"AAPL", "GOOGL"}

    def test_version_increments(self):
        """Test that version counter increments."""
        cache = PriceCache()
        v0 = cache.version
        cache.update("AAPL", 190.00)
        assert cache.version == v0 + 1
        cache.update("AAPL", 191.00)
        assert cache.version == v0 + 2

    def test_get_price_convenience(self):
        """Test the convenience get_price method."""
        cache = PriceCache()
        cache.update("AAPL", 190.50)
        assert cache.get_price("AAPL") == 190.50
        assert cache.get_price("NOPE") is None

    def test_len(self):
        """Test __len__ method."""
        cache = PriceCache()
        assert len(cache) == 0
        cache.update("AAPL", 190.00)
        assert len(cache) == 1
        cache.update("GOOGL", 175.00)
        assert len(cache) == 2

    def test_contains(self):
        """Test __contains__ method."""
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        assert "AAPL" in cache
        assert "GOOGL" not in cache

    def test_custom_timestamp(self):
        """Test updating with a custom timestamp."""
        cache = PriceCache()
        custom_ts = 1234567890.0
        update = cache.update("AAPL", 190.50, timestamp=custom_ts)
        assert update.timestamp == custom_ts

    def test_price_rounding(self):
        """Test that prices are rounded to 2 decimal places."""
        cache = PriceCache()
        update = cache.update("AAPL", 190.12345)
        assert update.price == 190.12

    def test_concurrent_updates_are_not_lost(self):
        """Concurrent writers must never clobber each other's version increment."""
        cache = PriceCache()
        n_threads = 8
        updates_per_thread = 200

        def worker(i: int) -> None:
            for j in range(updates_per_thread):
                cache.update(f"T{i}", float(j))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert cache.version == n_threads * updates_per_thread

    def test_version_read_concurrent_with_writes_does_not_raise(self):
        """Reading version while another thread writes concurrently must not raise or hang."""
        cache = PriceCache()
        stop = threading.Event()

        def writer() -> None:
            while not stop.is_set():
                cache.update("AAPL", 190.0)

        writer_thread = threading.Thread(target=writer)
        writer_thread.start()
        try:
            for _ in range(2000):
                assert isinstance(cache.version, int)
        finally:
            stop.set()
            writer_thread.join(timeout=2)


class TestVersionCounter:
    """The version counter must reflect every mutation, not just updates."""

    def test_remove_bumps_version(self):
        """A removal is a change; without a bump it is invisible to version-based
        consumers until some unrelated ticker happens to tick."""
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        before = cache.version

        cache.remove("AAPL")

        assert cache.version == before + 1

    def test_removing_absent_ticker_does_not_bump(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        before = cache.version
        cache.remove("NOPE")
        assert cache.version == before


class TestTimestampHandling:
    def test_explicit_zero_timestamp_is_honoured(self):
        """0.0 is a legitimate epoch timestamp, not 'unset'."""
        cache = PriceCache()
        update = cache.update("AAPL", 190.0, timestamp=0.0)
        assert update.timestamp == 0.0

    def test_none_timestamp_uses_wall_clock(self):
        cache = PriceCache()
        update = cache.update("AAPL", 190.0, timestamp=None)
        assert update.timestamp > 0


class TestReferencePrice:
    """Reference prices back the watchlist's 'daily change %' column."""

    def test_first_price_becomes_the_reference(self):
        cache = PriceCache()
        first = cache.update("AAPL", 190.0)
        assert first.reference_price == 190.0
        assert first.daily_change_percent == 0.0

    def test_reference_is_stable_across_updates(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        later = cache.update("AAPL", 209.0)
        assert later.reference_price == 190.0
        assert later.daily_change == 19.0
        assert later.daily_change_percent == 10.0

    def test_set_reference_before_first_update(self):
        cache = PriceCache()
        cache.set_reference("AAPL", 200.0)
        update = cache.update("AAPL", 190.0)
        assert update.reference_price == 200.0
        assert update.daily_change == -10.0
        assert update.daily_change_percent == -5.0

    def test_set_reference_rewrites_existing_update(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        cache.set_reference("AAPL", 200.0)
        current = cache.get("AAPL")
        assert current.reference_price == 200.0
        assert current.price == 190.0

    def test_remove_clears_reference_so_readd_restarts_the_session(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        cache.remove("AAPL")
        readded = cache.update("AAPL", 250.0)
        assert readded.reference_price == 250.0
        assert readded.daily_change == 0.0
