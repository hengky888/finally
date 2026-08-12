"""Tests for the FastAPI application wiring."""

from __future__ import annotations

import logging
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import (
    configure_logging,
    create_app,
    get_market_source,
    get_price_cache,
    load_initial_tickers,
)
from app.market import MarketDataSource, PriceCache
from app.market.seed_prices import DEFAULT_WATCHLIST


class TestAppConstruction:
    """The app must be usable before lifespan runs (import-time safety)."""

    def test_create_app_builds_cache_eagerly(self):
        app = create_app()
        assert isinstance(app.state.price_cache, PriceCache)
        assert app.state.market_source is None

    def test_stream_route_registered(self):
        app = create_app()
        paths = {route.path for route in app.routes}
        assert "/api/stream/prices" in paths
        assert "/api/health" in paths

    def test_each_app_gets_its_own_cache(self):
        """Regression guard: a shared module-level router/cache would break isolation."""
        a, b = create_app(), create_app()
        assert a.state.price_cache is not b.state.price_cache

    def test_initial_tickers_are_the_seed_watchlist(self):
        assert load_initial_tickers() == DEFAULT_WATCHLIST
        # A copy, so a caller mutating it cannot corrupt the seed constant.
        load_initial_tickers().append("ZZZZ")
        assert "ZZZZ" not in DEFAULT_WATCHLIST


class TestLifespan:
    """Startup must actually produce a running, priced market."""

    def test_health_reports_priced_tickers_after_startup(self):
        app = create_app()
        with TestClient(app) as client:
            response = client.get("/api/health")
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "ok"
            # The feed seeds the cache during start(), so this is non-zero
            # immediately rather than after the first tick.
            assert body["priced_tickers"] == len(DEFAULT_WATCHLIST)

    def test_source_started_and_stopped_with_the_app(self):
        app = create_app()
        with TestClient(app):
            source = app.state.market_source
            assert isinstance(source, MarketDataSource)
            assert set(source.get_tickers()) == set(DEFAULT_WATCHLIST)
        # Lifespan shutdown must release the source rather than leak the task.
        assert app.state.market_source is None

    def test_health_before_startup_reports_zero(self):
        """Health must not explode when the feed has not started."""
        app = create_app()
        client = TestClient(app)  # no context manager -> no lifespan
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "priced_tickers": 0}

    def test_prices_are_live_after_startup(self):
        app = create_app()
        with TestClient(app) as client:
            cache: PriceCache = app.state.price_cache
            assert cache.get_price("AAPL") is not None
            assert client.get("/api/health").json()["priced_tickers"] > 0


class TestDependencies:
    """The DI accessors downstream routers will use."""

    def test_accessors_return_lifespan_objects(self):
        app = create_app()
        with TestClient(app):

            class _Req:
                pass

            request = _Req()
            request.app = app
            assert get_price_cache(request) is app.state.price_cache
            assert get_market_source(request) is app.state.market_source


class TestLogging:
    """Log configuration is main.py's job; without it the subsystem is silent."""

    def test_configure_logging_attaches_a_handler(self):
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        assert not root.handlers

        configure_logging()
        assert root.handlers

    def test_log_level_env_var_is_honoured(self):
        with patch.dict(os.environ, {"LOG_LEVEL": "warning"}, clear=False):
            configure_logging()
            assert logging.getLogger().level == logging.WARNING
        with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}, clear=False):
            configure_logging()
            assert logging.getLogger().level == logging.DEBUG


@pytest.fixture(autouse=True)
def _restore_logging():
    """Keep logging mutations from leaking into other tests."""
    root = logging.getLogger()
    level, handlers = root.level, root.handlers[:]
    yield
    root.setLevel(level)
    root.handlers[:] = handlers
