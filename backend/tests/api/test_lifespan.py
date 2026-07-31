"""The real startup path: database first, then the market and snapshot tasks."""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import positions, watchlist
from app.main import create_app


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A temp database path and a snapshot interval that never fires."""
    db_path = tmp_path / "db" / "finally.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("SNAPSHOT_INTERVAL", "3600")
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    monkeypatch.setenv("STATIC_DIR", str(tmp_path / "absent"))
    return db_path


def test_lifespan_creates_the_database_and_starts_the_market(env):
    stopped = []

    with TestClient(create_app()) as client:
        assert env.exists(), "the database is created during startup"
        assert client.get("/api/health").json() == {"status": "ok"}

        watchlist_body = client.get("/api/watchlist").json()
        assert len(watchlist_body) == 10
        assert all(entry["price"] > 0 for entry in watchlist_body)

        app = client.app
        source = app.state.market_source
        assert source.get_tickers()
        assert not app.state.snapshot_task.done()

        real_stop = source.stop

        async def recording_stop():
            stopped.append(True)
            await real_stop()

        source.stop = recording_stop

    assert app.state.snapshot_task.cancelled(), "the snapshot task is cancelled on shutdown"
    assert stopped == [True], "the market data source is stopped on shutdown"


def test_lifespan_prices_held_tickers_outside_the_watchlist(env, tmp_path):
    _seed_held_but_unwatched(env)

    with TestClient(create_app()) as client:
        tickers = client.app.state.market_source.get_tickers()
        assert "AAPL" in tickers
        assert "AAPL" not in [e["ticker"] for e in client.get("/api/watchlist").json()]

        position = client.get("/api/portfolio").json()["positions"][0]
        assert position["current_price"] > 0


def test_missing_static_directory_does_not_stop_boot(env):
    with TestClient(create_app()) as client:
        assert client.get("/api/health").status_code == 200


def test_static_files_are_served_with_api_routes_taking_precedence(env, tmp_path, monkeypatch):
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<h1>FinAlly</h1>", encoding="utf-8")
    monkeypatch.setenv("STATIC_DIR", str(static_dir))

    with TestClient(create_app()) as client:
        assert client.get("/").text == "<h1>FinAlly</h1>"
        assert client.get("/api/health").json() == {"status": "ok"}


def test_api_routes_are_registered_before_the_static_mount(env, tmp_path, monkeypatch):
    """StaticFiles at / matches every path, so it must be matched last."""
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    monkeypatch.setenv("STATIC_DIR", str(static_dir))

    routes = create_app().routes
    static_index = next(i for i, r in enumerate(routes) if getattr(r, "name", "") == "static")
    api_paths = {r.path: i for i, r in enumerate(routes) if getattr(r, "path", "").startswith("/api")}

    assert "/api/chat" in api_paths, "the LLM router is mounted"
    assert "/api/stream/prices" in api_paths
    assert max(api_paths.values()) < static_index


def _seed_held_but_unwatched(db_path: Path) -> None:
    """Create a database holding AAPL that is not on the watchlist."""
    from app.db import init_db

    init_db(str(db_path))
    conn = sqlite3.connect(db_path, isolation_level="")
    conn.row_factory = sqlite3.Row
    with conn:
        watchlist.remove(conn, "AAPL")
        positions.upsert(conn, "AAPL", 5.0, 100.0)
    conn.close()
