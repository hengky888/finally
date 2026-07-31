"""Watchlist routes."""

from app.db import watchlist


def test_get_watchlist_returns_seeded_tickers_with_prices(client, conn):
    response = client.get("/api/watchlist")

    assert response.status_code == 200
    body = response.json()
    assert [entry["ticker"] for entry in body] == watchlist.list_tickers(conn)
    aapl = next(entry for entry in body if entry["ticker"] == "AAPL")
    assert aapl["price"] == 100.0
    assert aapl["direction"] == "flat"


def test_add_ticker(client, conn):
    client.delete("/api/watchlist/PYPL")

    response = client.post("/api/watchlist", json={"ticker": "pypl"})

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "PYPL"
    assert body["added"] is True
    assert body["price"] == 25.0
    assert "PYPL" in watchlist.list_tickers(conn)


def test_add_unknown_ticker_is_a_400(client):
    response = client.post("/api/watchlist", json={"ticker": "ZZZZ"})

    assert response.status_code == 400
    assert "not a symbol this market trades" in response.json()["detail"]


def test_remove_ticker(client, conn, cache):
    response = client.delete("/api/watchlist/AAPL")

    assert response.status_code == 200
    assert response.json() == {"ticker": "AAPL", "removed": True, "still_priced": False}
    assert "AAPL" not in watchlist.list_tickers(conn)
    assert cache.get_price("AAPL") is None


def test_removing_a_held_ticker_keeps_it_priced_and_valued(client, cache):
    client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 5, "side": "buy"})

    response = client.delete("/api/watchlist/AAPL")

    assert response.json()["still_priced"] is True
    assert cache.get_price("AAPL") == 100.0
    position = client.get("/api/portfolio").json()["positions"][0]
    assert position["ticker"] == "AAPL"
    assert position["current_price"] == 100.0


def test_remove_absent_ticker_reports_no_removal(client):
    response = client.delete("/api/watchlist/PYPL")

    assert response.status_code == 200
    assert response.json()["removed"] is False
