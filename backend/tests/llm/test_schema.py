"""Structured output parsing: valid schemas and malformed replies."""

import pytest

from app.llm.errors import LLMError
from app.llm.schema import AssistantResponse
from app.llm.service import _parse


def test_message_only_response_parses():
    response = _parse('{"message": "Your portfolio is up 2%."}')
    assert response.message == "Your portfolio is up 2%."
    assert response.trades == []
    assert response.watchlist_changes == []


def test_full_response_parses():
    raw = """
    {"message": "Buying.",
     "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 10}],
     "watchlist_changes": [{"ticker": "PYPL", "action": "add"}]}
    """
    response = _parse(raw)
    assert response.trades[0].ticker == "AAPL"
    assert response.trades[0].side == "buy"
    assert response.trades[0].quantity == 10
    assert response.watchlist_changes[0].action == "add"


@pytest.mark.parametrize(
    "raw",
    [
        "not json at all",
        "",
        None,
        "{}",
        '{"message": "Hi", "trades": [{"ticker": "AAPL", "side": "short", "quantity": 1}]}',
        '{"message": "Hi", "watchlist_changes": [{"ticker": "AAPL", "action": "star"}]}',
    ],
)
def test_malformed_response_raises_llm_error(raw):
    with pytest.raises(LLMError):
        _parse(raw)


def test_schema_serializes_to_the_planned_shape():
    dumped = AssistantResponse(message="hi").model_dump()
    assert set(dumped) == {"message", "trades", "watchlist_changes"}
