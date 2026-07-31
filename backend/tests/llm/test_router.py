"""The /api/chat route, in the mock mode the E2E suite runs in."""

from app.db import positions
from app.llm.client import MISSING_KEY
from tests.llm.conftest import make_settings


def test_plain_message_returns_a_reply(client):
    response = client.post("/api/chat", json={"message": "how am i doing?"})
    assert response.status_code == 200
    body = response.json()
    assert body["message"]
    assert body["actions"] is None


def test_chat_can_execute_a_trade(client, conn):
    body = client.post("/api/chat", json={"message": "buy 10 AAPL"}).json()
    assert body["actions"]["trades"] == [
        {"ticker": "AAPL", "side": "buy", "quantity": 10.0, "price": 100.0}
    ]
    assert positions.get(conn, "AAPL")["quantity"] == 10.0


def test_chat_can_change_the_watchlist(client):
    body = client.post("/api/chat", json={"message": "add PYPL to my watchlist"}).json()
    assert body["actions"]["watchlist_changes"] == [{"ticker": "PYPL", "action": "add"}]


def test_rejected_trade_returns_200_with_an_error(client):
    body = client.post("/api/chat", json={"message": "buy 5000 AAPL"}).json()
    assert "trades" not in body["actions"]
    assert "Insufficient cash" in body["actions"]["errors"][0]


def test_missing_api_key_returns_a_displayable_error(app, client):
    app.state.settings = make_settings(llm_mock=False, openrouter_api_key="")
    response = client.post("/api/chat", json={"message": "hello"})
    assert response.status_code == 503
    assert response.json()["detail"] == MISSING_KEY


def test_message_is_required(client):
    assert client.post("/api/chat", json={}).status_code == 422
