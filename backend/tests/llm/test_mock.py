"""Mock mode: no network call, and the same reply every time."""

from app.llm.client import complete
from app.llm.mock import mock_completion
from app.llm.schema import AssistantResponse


def _reply(text: str) -> AssistantResponse:
    return AssistantResponse.model_validate_json(mock_completion([{"role": "user", "content": text}]))


def test_buy_request_produces_a_trade():
    reply = _reply("buy 10 AAPL please")
    assert [(t.ticker, t.side, t.quantity) for t in reply.trades] == [("AAPL", "buy", 10.0)]


def test_sell_request_produces_a_sell():
    reply = _reply("sell 3 MSFT")
    assert [(t.ticker, t.side, t.quantity) for t in reply.trades] == [("MSFT", "sell", 3.0)]


def test_quantity_defaults_to_one_share():
    assert _reply("buy TSLA").trades[0].quantity == 1.0


def test_watchlist_add_and_remove():
    assert _reply("add PYPL to my watchlist").watchlist_changes[0].action == "add"
    assert _reply("remove PYPL from my watchlist").watchlist_changes[0].action == "remove"


def test_plain_question_asks_for_nothing():
    reply = _reply("how am i doing today?")
    assert reply.trades == []
    assert reply.watchlist_changes == []
    assert reply.message


def test_the_same_message_always_gives_the_same_reply():
    assert mock_completion([{"role": "user", "content": "buy 10 AAPL"}]) == mock_completion(
        [{"role": "user", "content": "buy 10 AAPL"}]
    )


async def test_mock_mode_never_calls_litellm(mock_settings, mocker):
    called = mocker.patch("app.llm.client.completion")
    raw = await complete([{"role": "user", "content": "buy 2 AAPL"}], mock_settings)
    called.assert_not_called()
    assert AssistantResponse.model_validate_json(raw).trades[0].ticker == "AAPL"
