"""Valuation and position math."""

import pytest

from app.db import positions, profile, snapshots, trades, watchlist
from app.services import TradeError, portfolio


def test_fresh_portfolio_is_all_cash(conn, cache):
    result = portfolio.get_portfolio(conn, cache)

    assert result["cash_balance"] == 10000.0
    assert result["positions"] == []
    assert result["total_value"] == 10000.0
    assert result["total_unrealized_pnl"] == 0.0


def test_position_valuation_formulas(conn, cache):
    with conn:
        positions.upsert(conn, "AAPL", 10.0, 80.0)

    position = portfolio.get_portfolio(conn, cache)["positions"][0]

    assert position["current_price"] == 100.0
    assert position["position_value"] == 1000.0
    assert position["unrealized_pnl"] == 200.0
    assert position["pnl_pct"] == pytest.approx(0.25)


def test_total_value_is_cash_plus_positions(conn, cache):
    with conn:
        positions.upsert(conn, "AAPL", 10.0, 80.0)
        positions.upsert(conn, "MSFT", 2.0, 150.0)

    result = portfolio.get_portfolio(conn, cache)

    assert result["total_value"] == pytest.approx(10000.0 + 1000.0 + 400.0)
    assert result["total_unrealized_pnl"] == pytest.approx(200.0 + 100.0)


def test_unpriced_position_falls_back_to_cost_basis(conn, cache):
    with conn:
        positions.upsert(conn, "PYPL", 4.0, 25.0)

    position = portfolio.get_portfolio(conn, cache)["positions"][0]

    assert position["current_price"] == 25.0
    assert position["unrealized_pnl"] == 0.0


def test_record_snapshot_writes_total_value(conn, cache):
    with conn:
        positions.upsert(conn, "AAPL", 10.0, 80.0)

    snapshot = portfolio.record_snapshot(conn, cache)

    assert snapshot["total_value"] == pytest.approx(11000.0)
    assert len(snapshots.list_all(conn)) == 1


def test_priced_set_is_watchlist_union_positions(conn):
    with conn:
        watchlist.remove(conn, "AAPL")
        positions.upsert(conn, "AAPL", 5.0, 90.0)

    tickers = portfolio.priced_tickers(conn)

    assert "AAPL" in tickers, "a held ticker stays priced after leaving the watchlist"
    assert "MSFT" in tickers


async def test_buy_debits_cash_and_opens_position(conn, cache, source):
    result = await portfolio.execute_trade(conn, cache, source, "AAPL", "buy", 10)

    assert result["price"] == 100.0
    assert result["cash_balance"] == pytest.approx(9000.0)
    assert result["position"]["quantity"] == 10.0
    assert result["position"]["avg_cost"] == 100.0
    assert profile.get(conn)["cash_balance"] == pytest.approx(9000.0)


async def test_buy_uses_quantity_weighted_average_cost(conn, cache, source):
    await portfolio.execute_trade(conn, cache, source, "AAPL", "buy", 10)
    cache.update("AAPL", 200.0)
    result = await portfolio.execute_trade(conn, cache, source, "AAPL", "buy", 30)

    # (10 * 100 + 30 * 200) / 40
    assert result["position"]["avg_cost"] == pytest.approx(175.0)
    assert result["position"]["quantity"] == pytest.approx(40.0)


async def test_sell_leaves_cost_basis_unchanged(conn, cache, source):
    await portfolio.execute_trade(conn, cache, source, "AAPL", "buy", 10)
    cache.update("AAPL", 150.0)
    result = await portfolio.execute_trade(conn, cache, source, "AAPL", "sell", 4)

    assert result["position"]["avg_cost"] == 100.0
    assert result["position"]["quantity"] == pytest.approx(6.0)
    assert result["cash_balance"] == pytest.approx(9000.0 + 600.0)


async def test_selling_everything_deletes_the_position(conn, cache, source):
    await portfolio.execute_trade(conn, cache, source, "AAPL", "buy", 10)
    result = await portfolio.execute_trade(conn, cache, source, "AAPL", "sell", 10)

    assert result["position"] is None
    assert positions.get(conn, "AAPL") is None


async def test_fractional_sell_to_zero_deletes_the_position(conn, cache, source):
    await portfolio.execute_trade(conn, cache, source, "AAPL", "buy", 0.3)
    await portfolio.execute_trade(conn, cache, source, "AAPL", "buy", 0.6)
    await portfolio.execute_trade(conn, cache, source, "AAPL", "sell", 0.9)

    assert positions.get(conn, "AAPL") is None


async def test_trade_writes_a_snapshot(conn, cache, source):
    await portfolio.execute_trade(conn, cache, source, "AAPL", "buy", 10)

    history = snapshots.list_all(conn)
    assert len(history) == 1
    assert history[0]["total_value"] == pytest.approx(10000.0)


async def test_unpriced_ticker_is_auto_added_to_the_watchlist(conn, cache, source):
    with conn:
        watchlist.remove(conn, "PYPL")

    result = await portfolio.execute_trade(conn, cache, source, "PYPL", "buy", 2)

    assert result["price"] == 25.0
    assert "PYPL" in watchlist.list_tickers(conn)


async def test_ticker_is_normalized(conn, cache, source):
    result = await portfolio.execute_trade(conn, cache, source, " aapl ", "buy", 1)

    assert result["ticker"] == "AAPL"


async def test_rejects_non_positive_quantity(conn, cache, source):
    with pytest.raises(TradeError, match="greater than zero"):
        await portfolio.execute_trade(conn, cache, source, "AAPL", "buy", 0)

    with pytest.raises(TradeError, match="greater than zero"):
        await portfolio.execute_trade(conn, cache, source, "AAPL", "buy", -5)


async def test_rejects_buy_exceeding_cash(conn, cache, source):
    with pytest.raises(TradeError, match="Insufficient cash"):
        await portfolio.execute_trade(conn, cache, source, "AAPL", "buy", 101)

    assert profile.get(conn)["cash_balance"] == 10000.0
    assert trades.list_recent(conn) == []


async def test_rejects_overselling(conn, cache, source):
    await portfolio.execute_trade(conn, cache, source, "AAPL", "buy", 5)

    with pytest.raises(TradeError, match="only 5 shares are held"):
        await portfolio.execute_trade(conn, cache, source, "AAPL", "sell", 6)

    assert positions.get(conn, "AAPL")["quantity"] == 5.0


async def test_rejects_selling_an_unheld_ticker(conn, cache, source):
    with pytest.raises(TradeError, match="only 0 shares are held"):
        await portfolio.execute_trade(conn, cache, source, "MSFT", "sell", 1)


async def test_rejects_unknown_symbol(conn, cache, source):
    with pytest.raises(TradeError, match="not a symbol this market trades"):
        await portfolio.execute_trade(conn, cache, source, "ZZZZ", "buy", 1)


async def test_rejects_malformed_symbol(conn, cache, source):
    with pytest.raises(TradeError, match="not a valid ticker symbol"):
        await portfolio.execute_trade(conn, cache, source, "not a ticker", "buy", 1)


async def test_rejects_unknown_side(conn, cache, source):
    with pytest.raises(TradeError, match="buy.*sell"):
        await portfolio.execute_trade(conn, cache, source, "AAPL", "hold", 1)


async def test_rejected_trade_does_not_add_to_the_watchlist(conn, cache, source):
    with conn:
        watchlist.remove(conn, "PYPL")

    with pytest.raises(TradeError, match="Insufficient cash"):
        await portfolio.execute_trade(conn, cache, source, "PYPL", "buy", 1000)

    assert "PYPL" not in watchlist.list_tickers(conn)


async def test_trade_writes_are_one_transaction(conn, cache, source, monkeypatch):
    """A failure after the cash debit must roll the whole trade back."""

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(snapshots, "append", boom)

    with pytest.raises(RuntimeError):
        await portfolio.execute_trade(conn, cache, source, "AAPL", "buy", 10)

    assert profile.get(conn)["cash_balance"] == 10000.0
    assert positions.get(conn, "AAPL") is None
    assert trades.list_recent(conn) == []
