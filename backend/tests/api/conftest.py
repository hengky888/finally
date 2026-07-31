"""Fixtures for API tests.

The app is built without running its lifespan, so the market data source and
the snapshot task never start. What the lifespan would set up is provided
here instead: a temp database, a hand-seeded cache and a fake source.
`tests/api/test_lifespan.py` covers the real startup path.
"""

import pytest
from fastapi.testclient import TestClient

from app.db import get_connection, init_db
from app.main import create_app
from tests.services.fake_source import seeded_cache, seeded_source


@pytest.fixture
def app(tmp_path):
    """App wired to a temp database, with the market subsystem faked."""
    init_db(str(tmp_path / "test.db"))
    application = create_app()
    cache = seeded_cache(application.state.price_cache)
    application.state.market_source = seeded_source(cache)
    return application


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def cache(app):
    return app.state.price_cache


@pytest.fixture
def conn(app):
    """Connection to the same database the app is using."""
    connection = get_connection()
    yield connection
    connection.close()
