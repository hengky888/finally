"""Fixtures for service layer tests: a temp database and a hand-seeded cache."""

import pytest

from app.db import get_connection, init_db
from app.market import PriceCache

from .fake_source import seeded_cache, seeded_source


@pytest.fixture
def conn(tmp_path):
    """Connection to a freshly seeded database."""
    init_db(str(tmp_path / "test.db"))
    connection = get_connection()
    yield connection
    connection.close()


@pytest.fixture
def cache():
    """Price cache holding the test universe, but not PYPL."""
    return seeded_cache(PriceCache())


@pytest.fixture
def source(cache):
    """Market data source already tracking whatever the cache holds."""
    return seeded_source(cache)
