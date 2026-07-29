"""Tests for the SSE streaming endpoint."""

import json

import pytest

from app.market.cache import PriceCache
from app.market.stream import _diff, _generate_events, create_stream_router


class _FakeClient:
    """Stand-in for starlette's Request.client."""

    def __init__(self, host: str = "127.0.0.1") -> None:
        self.host = host


class _FakeRequest:
    """Minimal stand-in for fastapi.Request that disconnects after N checks."""

    def __init__(self, disconnect_after: int = 1) -> None:
        self.client = _FakeClient()
        self._checks = 0
        self._disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self._checks += 1
        return self._checks > self._disconnect_after


def _parse(event: str) -> dict:
    assert event.startswith("data: ")
    return json.loads(event[len("data: ") :].strip())


class TestDiff:
    """Unit tests for the per-connection _diff payload builder."""

    def test_first_tick_is_flat(self):
        """With no prior price for this connection, the tick reports itself as the baseline."""
        payload = _diff("AAPL", 190.0, None, 1234.0)
        assert payload["direction"] == "flat"
        assert payload["previous_price"] == 190.0
        assert payload["change"] == 0.0

    def test_direction_up(self):
        payload = _diff("AAPL", 191.0, 190.0, 1234.0)
        assert payload["direction"] == "up"
        assert payload["change"] == 1.0

    def test_direction_down(self):
        payload = _diff("AAPL", 189.0, 190.0, 1234.0)
        assert payload["direction"] == "down"
        assert payload["change"] == -1.0

    def test_direction_flat_when_unchanged(self):
        payload = _diff("AAPL", 190.0, 190.0, 1234.0)
        assert payload["direction"] == "flat"
        assert payload["change"] == 0.0

    def test_change_percent(self):
        payload = _diff("AAPL", 195.0, 100.0, 1234.0)
        assert payload["change_percent"] == 95.0

    def test_change_percent_zero_previous(self):
        """A zero previous price must not raise ZeroDivisionError."""
        payload = _diff("AAPL", 100.0, 0.0, 1234.0)
        assert payload["change_percent"] == 0.0

    def test_fields_present(self):
        payload = _diff("AAPL", 190.0, 189.0, 1234.5)
        assert set(payload) == {
            "ticker",
            "price",
            "previous_price",
            "change",
            "change_percent",
            "direction",
            "timestamp",
        }
        assert payload["ticker"] == "AAPL"
        assert payload["timestamp"] == 1234.5


@pytest.mark.asyncio
class TestGenerateEvents:
    """Tests for the SSE event generator loop."""

    async def test_yields_retry_then_data(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        request = _FakeRequest(disconnect_after=1)

        events = [event async for event in _generate_events(cache, request, interval=0.001)]

        assert events[0] == "retry: 1000\n\n"
        assert len(events) == 2
        body = _parse(events[1])
        assert body["seq"] == 1
        assert body["prices"]["AAPL"]["direction"] == "flat"

    async def test_no_data_event_when_cache_empty(self):
        """An empty priced set produces no data frame, only the initial retry directive."""
        cache = PriceCache()
        request = _FakeRequest(disconnect_after=1)

        events = [event async for event in _generate_events(cache, request, interval=0.001)]

        assert events == ["retry: 1000\n\n"]

    async def test_immediate_disconnect_yields_only_retry(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        request = _FakeRequest(disconnect_after=0)

        events = [event async for event in _generate_events(cache, request, interval=0.001)]

        assert events == ["retry: 1000\n\n"]

    async def test_direction_relative_to_last_sent_price(self):
        """direction is computed against what THIS connection last saw, not the cache history."""
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        request = _FakeRequest(disconnect_after=2)
        gen = _generate_events(cache, request, interval=0.001)

        retry_event = await gen.__anext__()
        assert retry_event == "retry: 1000\n\n"

        first = _parse(await gen.__anext__())
        assert first["prices"]["AAPL"]["direction"] == "flat"
        assert first["seq"] == 1

        # Move the price between ticks -- the next event should be relative to 190.0,
        # not to whatever the cache's own previous_price bookkeeping says.
        cache.update("AAPL", 195.0)

        second = _parse(await gen.__anext__())
        assert second["prices"]["AAPL"]["direction"] == "up"
        assert second["prices"]["AAPL"]["previous_price"] == 190.0
        assert second["prices"]["AAPL"]["price"] == 195.0
        assert second["seq"] == 2

        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

    async def test_re_added_ticker_starts_flat(self):
        """A ticker that drops out of the priced set for a tick, then returns, is treated as new."""
        cache = PriceCache()
        cache.update("AAPL", 190.0)
        cache.update("TSLA", 300.0)
        request = _FakeRequest(disconnect_after=3)
        gen = _generate_events(cache, request, interval=0.001)

        await gen.__anext__()  # retry
        first = _parse(await gen.__anext__())
        assert set(first["prices"]) == {"AAPL", "TSLA"}

        # TSLA leaves the priced set for a full tick -- the server observes its absence.
        cache.remove("TSLA")
        second = _parse(await gen.__anext__())
        assert set(second["prices"]) == {"AAPL"}

        # TSLA comes back with a new price -- from this connection's perspective it's new.
        cache.update("TSLA", 310.0)
        third = _parse(await gen.__anext__())
        assert third["prices"]["TSLA"]["direction"] == "flat"
        assert third["prices"]["TSLA"]["previous_price"] == 310.0


class TestCreateStreamRouter:
    """Tests for router construction."""

    def test_router_has_prices_route(self):
        cache = PriceCache()
        router = create_stream_router(cache)
        paths = [route.path for route in router.routes]
        assert "/api/stream/prices" in paths

    def test_fresh_router_per_call(self):
        """Each call must return an independent router so tests can build multiple apps."""
        cache = PriceCache()
        router1 = create_stream_router(cache)
        router2 = create_stream_router(cache)
        assert router1 is not router2
        assert router1.routes[0] is not router2.routes[0]
