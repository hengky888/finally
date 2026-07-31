"""Auto-execution: the actions payload records what happened, not what was asked."""

from app.db import positions, profile, watchlist
from app.llm.executor import execute
from app.llm.schema import AssistantResponse


def response(**kwargs) -> AssistantResponse:
    return AssistantResponse(message="ok", **kwargs)


async def test_trade_executes_and_is_reported(conn, cache, source):
    actions = await execute(
        conn, cache, source, response(trades=[{"ticker": "AAPL", "side": "buy", "quantity": 10}])
    )
    assert actions == {"trades": [{"ticker": "AAPL", "side": "buy", "quantity": 10.0, "price": 100.0}]}
    assert positions.get(conn, "AAPL")["quantity"] == 10.0
    assert profile.get(conn)["cash_balance"] == 9000.0


async def test_watchlist_changes_apply(conn, cache, source):
    actions = await execute(
        conn,
        cache,
        source,
        response(
            watchlist_changes=[
                {"ticker": "PYPL", "action": "add"},
                {"ticker": "AAPL", "action": "remove"},
            ]
        ),
    )
    assert actions["watchlist_changes"] == [
        {"ticker": "PYPL", "action": "add"},
        {"ticker": "AAPL", "action": "remove"},
    ]
    tickers = watchlist.list_tickers(conn)
    assert "PYPL" in tickers
    assert "AAPL" not in tickers


async def test_rejected_trade_is_an_error_not_a_trade(conn, cache, source):
    actions = await execute(
        conn, cache, source, response(trades=[{"ticker": "AAPL", "side": "buy", "quantity": 500}])
    )
    assert "trades" not in actions
    assert len(actions["errors"]) == 1
    assert "Insufficient cash" in actions["errors"][0]
    assert positions.get(conn, "AAPL") is None


async def test_partial_failure_records_two_trades_and_one_error(conn, cache, source):
    actions = await execute(
        conn,
        cache,
        source,
        response(
            trades=[
                {"ticker": "AAPL", "side": "buy", "quantity": 10},
                {"ticker": "MSFT", "side": "buy", "quantity": 900},
                {"ticker": "TSLA", "side": "buy", "quantity": 4},
            ]
        ),
    )
    assert [t["ticker"] for t in actions["trades"]] == ["AAPL", "TSLA"]
    assert len(actions["errors"]) == 1
    assert "MSFT" in actions["errors"][0]
    assert positions.get(conn, "MSFT") is None


async def test_unknown_symbol_is_an_error(conn, cache, source):
    actions = await execute(
        conn, cache, source, response(trades=[{"ticker": "ZZZZ", "side": "buy", "quantity": 1}])
    )
    assert actions["errors"]
    assert "trades" not in actions


async def test_no_requested_actions_gives_no_payload(conn, cache, source):
    assert await execute(conn, cache, source, response()) is None
