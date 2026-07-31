"""Every service write must survive the connection that made it.

Accessors do not commit, so a write outside `with conn:` is discarded silently
when the connection closes. Reading back through the SAME connection would
return the uncommitted row and pass regardless, so every assertion here opens a
second connection.
"""

import pytest

from app.db import get_connection, positions, profile, snapshots, watchlist
from app.services import portfolio, watchlist_service


@pytest.fixture
def other_conn():
    """A second connection to the same database, opened per assertion."""
    connection = get_connection()
    yield connection
    connection.close()


async def test_trade_survives_the_writing_connection(conn, cache, source, other_conn):
    await portfolio.execute_trade(conn, cache, source, "AAPL", "buy", 10)
    conn.close()

    assert profile.get(other_conn)["cash_balance"] == pytest.approx(9000.0)
    assert positions.get(other_conn, "AAPL")["quantity"] == 10.0
    assert len(snapshots.list_all(other_conn)) == 1


async def test_sell_that_closes_a_position_survives(conn, cache, source, other_conn):
    await portfolio.execute_trade(conn, cache, source, "AAPL", "buy", 10)
    await portfolio.execute_trade(conn, cache, source, "AAPL", "sell", 10)
    conn.close()

    assert positions.get(other_conn, "AAPL") is None
    assert profile.get(other_conn)["cash_balance"] == pytest.approx(10000.0)


async def test_auto_added_watchlist_ticker_survives(conn, cache, source, other_conn):
    with conn:
        watchlist.remove(conn, "PYPL")
    await portfolio.execute_trade(conn, cache, source, "PYPL", "buy", 2)
    conn.close()

    assert "PYPL" in watchlist.list_tickers(other_conn)


async def test_watchlist_add_survives(conn, cache, source, other_conn):
    await watchlist_service.add_ticker(conn, cache, source, "PYPL")
    conn.close()

    assert "PYPL" in watchlist.list_tickers(other_conn)


async def test_watchlist_remove_survives(conn, cache, source, other_conn):
    await watchlist_service.remove_ticker(conn, cache, source, "AAPL")
    conn.close()

    assert "AAPL" not in watchlist.list_tickers(other_conn)


def test_recorded_snapshot_survives(conn, cache, other_conn):
    portfolio.record_snapshot(conn, cache)
    conn.close()

    assert len(snapshots.list_all(other_conn)) == 1
