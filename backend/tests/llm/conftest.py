"""Fixtures for the LLM tests.

The chat router is mounted on a bare app rather than the real one, so these
tests exercise the chat pipeline without depending on how `main.py` is wired.
No test reaches the network: `app.llm.client.completion` is never called except
where a test patches it.
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import get_connection, init_db
from app.llm import chat_router
from tests.services.fake_source import seeded_cache, seeded_source


def make_settings(*, llm_mock: bool = True, openrouter_api_key: str = "test-key") -> Settings:
    """Settings with only the fields the chat pipeline reads set meaningfully."""
    return Settings(
        db_path=":memory:",
        static_dir=Path("static"),
        snapshot_interval=30.0,
        massive_api_key="",
        openrouter_api_key=openrouter_api_key,
        llm_mock=llm_mock,
    )


@pytest.fixture
def mock_settings():
    return make_settings()


@pytest.fixture
def cache():
    from app.market import PriceCache

    return seeded_cache(PriceCache())


@pytest.fixture
def source(cache):
    return seeded_source(cache)


@pytest.fixture
def conn(tmp_path):
    """Connection to a freshly seeded temp database."""
    init_db(str(tmp_path / "test.db"))
    connection = get_connection()
    yield connection
    connection.close()


@pytest.fixture
def app(conn, cache, source, mock_settings):
    """A minimal app carrying just what the chat route's dependencies need."""
    application = FastAPI()
    application.state.settings = mock_settings
    application.state.price_cache = cache
    application.state.market_source = source
    application.include_router(chat_router)
    return application


@pytest.fixture
def client(app):
    return TestClient(app)
