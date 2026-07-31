"""Portfolio routes: shapes, status codes and rejections."""

import pytest

from app.db import positions, profile


def test_get_portfolio_shape(client):
    response = client.get("/api/portfolio")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"cash_balance", "positions", "total_value", "total_unrealized_pnl"}
    assert body["cash_balance"] == 10000.0
    assert body["total_value"] == 10000.0


def test_get_portfolio_position_shape(client, conn):
    with conn:
        positions.upsert(conn, "AAPL", 10.0, 80.0)

    position = client.get("/api/portfolio").json()["positions"][0]

    assert set(position) == {
        "ticker",
        "quantity",
        "avg_cost",
        "current_price",
        "position_value",
        "unrealized_pnl",
        "pnl_pct",
    }
    assert position["position_value"] == 1000.0


def test_trade_buy_returns_the_fill(client, conn):
    response = client.post(
        "/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 10, "side": "buy"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AAPL"
    assert body["side"] == "buy"
    assert body["quantity"] == 10.0
    assert body["price"] == 100.0
    assert body["cash_balance"] == pytest.approx(9000.0)
    assert body["position"]["avg_cost"] == 100.0
    assert body["total_value"] == pytest.approx(10000.0)
    assert profile.get(conn)["cash_balance"] == pytest.approx(9000.0)


def test_trade_sell_returns_the_fill(client):
    client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 10, "side": "buy"})

    response = client.post(
        "/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 10, "side": "sell"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["position"] is None
    assert body["cash_balance"] == pytest.approx(10000.0)


def test_trade_ignores_a_client_supplied_price(client, cache):
    cache.update("AAPL", 123.45)

    body = client.post(
        "/api/portfolio/trade",
        json={"ticker": "AAPL", "quantity": 1, "side": "buy", "price": 1.0},
    ).json()

    assert body["price"] == 123.45


@pytest.mark.parametrize(
    ("order", "message"),
    [
        ({"ticker": "AAPL", "quantity": 0, "side": "buy"}, "greater than zero"),
        ({"ticker": "AAPL", "quantity": -1, "side": "buy"}, "greater than zero"),
        ({"ticker": "AAPL", "quantity": 1000, "side": "buy"}, "Insufficient cash"),
        ({"ticker": "AAPL", "quantity": 1, "side": "sell"}, "shares are held"),
        ({"ticker": "ZZZZ", "quantity": 1, "side": "buy"}, "not a symbol this market trades"),
        ({"ticker": "!!", "quantity": 1, "side": "buy"}, "not a valid ticker symbol"),
        ({"ticker": "AAPL", "quantity": 1, "side": "hold"}, "buy"),
    ],
)
def test_trade_rejections_return_400_with_a_readable_message(client, order, message):
    response = client.post("/api/portfolio/trade", json=order)

    assert response.status_code == 400
    assert message in response.json()["detail"]


def test_rejected_trade_leaves_the_portfolio_untouched(client):
    client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 1000, "side": "buy"})

    body = client.get("/api/portfolio").json()
    assert body["cash_balance"] == 10000.0
    assert body["positions"] == []


def test_malformed_body_is_a_422(client):
    response = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "side": "buy"})

    assert response.status_code == 422


def test_history_is_empty_then_grows_with_trades(client):
    assert client.get("/api/portfolio/history").json() == []

    client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 1, "side": "buy"})

    history = client.get("/api/portfolio/history").json()
    assert len(history) == 1
    assert set(history[0]) == {"id", "total_value", "recorded_at"}
    assert history[0]["total_value"] == pytest.approx(10000.0)
