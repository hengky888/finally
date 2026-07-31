"""The periodic portfolio snapshot writer."""

import asyncio

from app.db import get_connection, init_db, positions, snapshots
from app.main import _snapshot_loop
from app.market import PriceCache
from tests.services.fake_source import seeded_cache


async def test_snapshot_loop_records_total_value(tmp_path):
    init_db(str(tmp_path / "test.db"))
    conn = get_connection()
    with conn:
        positions.upsert(conn, "AAPL", 10.0, 80.0)

    task = asyncio.create_task(_snapshot_loop(seeded_cache(PriceCache()), 0.01))
    await asyncio.sleep(0.05)
    task.cancel()

    history = snapshots.list_all(conn)
    conn.close()
    assert history, "the loop writes snapshots on its interval"
    assert history[0]["total_value"] == 11000.0


async def test_snapshot_loop_survives_a_failure(tmp_path, monkeypatch):
    init_db(str(tmp_path / "test.db"))
    calls = []

    def failing_append(conn, total_value):
        calls.append(total_value)
        raise RuntimeError("disk full")

    monkeypatch.setattr(snapshots, "append", failing_append)

    task = asyncio.create_task(_snapshot_loop(seeded_cache(PriceCache()), 0.01))
    await asyncio.sleep(0.05)
    assert not task.done(), "one bad snapshot does not kill the loop"
    task.cancel()

    assert len(calls) > 1
