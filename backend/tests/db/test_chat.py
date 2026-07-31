"""Tests for the chat messages accessor."""

from app.db import chat

ACTIONS = {
    "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 10, "price": 190.12}],
    "watchlist_changes": [{"ticker": "PYPL", "action": "add"}],
    "errors": ["Insufficient cash to buy 10 TSLA"],
}


def test_append_returns_the_new_row(conn):
    message = chat.append(conn, "user", "buy 10 AAPL")
    assert message["role"] == "user"
    assert message["content"] == "buy 10 AAPL"
    assert message["actions"] is None
    assert message["id"]
    assert message["created_at"]


def test_append_does_not_expose_user_id(conn):
    message = chat.append(conn, "user", "hello")
    assert set(message) == {"id", "role", "content", "actions", "created_at"}


def test_actions_round_trip_as_json(conn):
    chat.append(conn, "assistant", "Bought 10 AAPL", ACTIONS)
    assert chat.list_recent(conn)[0]["actions"] == ACTIONS


def test_actions_are_stored_as_a_json_string(conn):
    chat.append(conn, "assistant", "done", ACTIONS)
    stored = conn.execute("SELECT actions FROM chat_messages").fetchone()["actions"]
    assert isinstance(stored, str)


def test_list_recent_is_oldest_first(conn):
    chat.append(conn, "user", "first")
    chat.append(conn, "assistant", "second")
    chat.append(conn, "user", "third")

    assert [m["content"] for m in chat.list_recent(conn)] == ["first", "second", "third"]


def test_list_recent_keeps_the_newest_messages(conn):
    for index in range(5):
        chat.append(conn, "user", str(index))

    assert [m["content"] for m in chat.list_recent(conn, limit=2)] == ["3", "4"]


def test_list_recent_defaults_to_twenty(conn):
    for index in range(25):
        chat.append(conn, "user", str(index))

    recent = chat.list_recent(conn)
    assert len(recent) == 20
    assert recent[0]["content"] == "5"


def test_list_recent_is_empty_on_a_fresh_database(conn):
    assert chat.list_recent(conn) == []
