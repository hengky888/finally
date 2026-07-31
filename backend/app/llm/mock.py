"""Deterministic canned responses for LLM_MOCK=true.

The mock returns the same JSON string the live model would, so parsing,
auto-execution and persistence all run through exactly one code path. A mock
reply can therefore place a real trade, which is what the E2E suite relies on.
"""

from __future__ import annotations

import re

from .schema import AssistantResponse, TradeInstruction, WatchlistInstruction

TICKER = re.compile(r"\b[A-Z]{2,5}\b")
NUMBER = re.compile(r"\d+(?:\.\d+)?")

ANALYSIS = (
    "Mock analysis: your positions and cash are shown in the portfolio panel. "
    "Ask me to buy or sell a ticker, or to add one to your watchlist."
)


def mock_completion(messages: list[dict]) -> str:
    """Answer the last message in the list with a canned structured reply."""
    return _response_for(messages[-1]["content"]).model_dump_json()


def _response_for(text: str) -> AssistantResponse:
    """Map the user's wording onto a fixed reply. Same input, same output."""
    lower = text.lower()
    ticker = _first_ticker(text)
    if ticker is None:
        return AssistantResponse(message=ANALYSIS)

    if "sell" in lower or "buy" in lower:
        side = "sell" if "sell" in lower else "buy"
        quantity = _first_number(text)
        return AssistantResponse(
            message=f"Executing a {side} of {quantity:g} {ticker}.",
            trades=[TradeInstruction(ticker=ticker, side=side, quantity=quantity)],
        )

    if "watchlist" in lower or "watch" in lower:
        action = "remove" if "remove" in lower or "drop" in lower else "add"
        return AssistantResponse(
            message=f"{action.capitalize()}ing {ticker} on your watchlist.",
            watchlist_changes=[WatchlistInstruction(ticker=ticker, action=action)],
        )

    return AssistantResponse(message=f"{ANALYSIS} You mentioned {ticker}.")


def _first_ticker(text: str) -> str | None:
    """The first uppercase word that looks like a symbol."""
    match = TICKER.search(text)
    return match.group(0) if match else None


def _first_number(text: str) -> float:
    """The first number in the message; one share when none is given."""
    match = NUMBER.search(text)
    return float(match.group(0)) if match else 1.0
