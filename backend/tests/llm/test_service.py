"""The whole chat flow, with the LiteLLM call replaced by a canned reply."""

import json
from types import SimpleNamespace

import pytest

from app.db import chat, positions
from app.llm.client import MISSING_KEY
from app.llm.errors import LLMError
from app.llm.service import handle_chat
from tests.llm.conftest import make_settings


def fake_completion(mocker, content):
    """Stand in for litellm.completion, returning `content` as the reply body."""
    reply = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    return mocker.patch("app.llm.client.completion", return_value=reply)


@pytest.fixture
def live_settings():
    return make_settings(llm_mock=False)


async def test_live_flow_executes_and_persists(conn, cache, source, live_settings, mocker):
    called = fake_completion(
        mocker,
        json.dumps(
            {
                "message": "Buying 5 AAPL.",
                "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 5}],
            }
        ),
    )
    result = await handle_chat(conn, cache, source, live_settings, "buy 5 AAPL")

    assert result["message"] == "Buying 5 AAPL."
    assert result["actions"]["trades"][0]["price"] == 100.0
    assert positions.get(conn, "AAPL")["quantity"] == 5.0

    history = chat.list_recent(conn)
    assert [(m["role"], m["content"]) for m in history] == [
        ("user", "buy 5 AAPL"),
        ("assistant", "Buying 5 AAPL."),
    ]
    assert history[1]["actions"] == result["actions"]
    assert called.call_count == 1


async def test_prompt_carries_the_model_and_provider(conn, cache, source, live_settings, mocker):
    called = fake_completion(mocker, '{"message": "hi"}')
    await handle_chat(conn, cache, source, live_settings, "hello")

    kwargs = called.call_args.kwargs
    assert kwargs["model"] == "openrouter/openai/gpt-oss-120b"
    assert kwargs["extra_body"] == {"provider": {"order": ["cerebras"]}}
    assert kwargs["messages"][0]["content"].startswith("You are FinAlly")
    assert "Cash: $10,000.00" in kwargs["messages"][1]["content"]
    assert kwargs["messages"][-1] == {"role": "user", "content": "hello"}


async def test_history_is_replayed_to_the_model(conn, cache, source, live_settings, mocker):
    with conn:
        chat.append(conn, "user", "what do i hold?")
        chat.append(conn, "assistant", "Nothing yet.")
    called = fake_completion(mocker, '{"message": "Still nothing."}')

    await handle_chat(conn, cache, source, live_settings, "and now?")

    assert called.call_args.kwargs["messages"][2:] == [
        {"role": "user", "content": "what do i hold?"},
        {"role": "assistant", "content": "Nothing yet."},
        {"role": "user", "content": "and now?"},
    ]


async def test_recorded_actions_omit_the_rejected_trade(
    conn, cache, source, live_settings, mocker
):
    fake_completion(
        mocker,
        json.dumps(
            {
                "message": "Rebalancing.",
                "trades": [
                    {"ticker": "AAPL", "side": "buy", "quantity": 10},
                    {"ticker": "MSFT", "side": "buy", "quantity": 900},
                ],
            }
        ),
    )
    result = await handle_chat(conn, cache, source, live_settings, "rebalance me")

    assert [t["ticker"] for t in result["actions"]["trades"]] == ["AAPL"]
    assert len(result["actions"]["errors"]) == 1
    stored = chat.list_recent(conn)[-1]["actions"]
    assert stored == result["actions"]


async def test_malformed_reply_is_a_handled_error(conn, cache, source, live_settings, mocker):
    fake_completion(mocker, "sorry, I cannot do JSON")
    with pytest.raises(LLMError):
        await handle_chat(conn, cache, source, live_settings, "hello")
    assert chat.list_recent(conn) == []


async def test_missing_api_key_fails_the_call_only(conn, cache, source, mocker):
    called = fake_completion(mocker, '{"message": "hi"}')
    settings = make_settings(llm_mock=False, openrouter_api_key="")

    with pytest.raises(LLMError) as raised:
        await handle_chat(conn, cache, source, settings, "hello")

    assert str(raised.value) == MISSING_KEY
    called.assert_not_called()


async def test_upstream_failure_is_a_handled_error(conn, cache, source, live_settings, mocker):
    mocker.patch("app.llm.client.completion", side_effect=RuntimeError("connection reset"))
    with pytest.raises(LLMError) as raised:
        await handle_chat(conn, cache, source, live_settings, "hello")
    assert "connection reset" in str(raised.value)


async def test_mock_mode_drives_a_real_trade(conn, cache, source, mock_settings, mocker):
    called = mocker.patch("app.llm.client.completion")
    result = await handle_chat(conn, cache, source, mock_settings, "buy 4 TSLA")

    called.assert_not_called()
    assert result["actions"]["trades"] == [
        {"ticker": "TSLA", "side": "buy", "quantity": 4.0, "price": 50.0}
    ]
    assert positions.get(conn, "TSLA")["quantity"] == 4.0
    assert chat.list_recent(conn)[-1]["actions"] == result["actions"]
