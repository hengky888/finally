"""The chat request flow (PLAN.md section 9).

Context and history in, model call, parse, auto-execute, persist what actually
happened, return the complete response. No token streaming.
"""

from __future__ import annotations

import sqlite3

from pydantic import ValidationError

from app.config import Settings
from app.db import chat
from app.market import MarketDataSource, PriceCache

from . import client, context, executor, prompt
from .errors import LLMError
from .schema import AssistantResponse

HISTORY_LIMIT = 20

MALFORMED = "The assistant replied in a format that could not be read. Please try again."


async def handle_chat(
    conn: sqlite3.Connection,
    cache: PriceCache,
    source: MarketDataSource,
    settings: Settings,
    user_message: str,
) -> dict:
    """Answer one user message, executing any actions it leads to."""
    messages = prompt.build_messages(
        context.build(conn, cache), chat.list_recent(conn, HISTORY_LIMIT), user_message
    )
    response = _parse(await client.complete(messages, settings))
    actions = await executor.execute(conn, cache, source, response)

    with conn:
        chat.append(conn, "user", user_message)
        chat.append(conn, "assistant", response.message, actions)

    return {"message": response.message, "actions": actions}


def _parse(raw: str | None) -> AssistantResponse:
    """Read the structured reply, or fail with a message the UI can show."""
    try:
        return AssistantResponse.model_validate_json(raw or "")
    except ValidationError as exc:
        raise LLMError(MALFORMED) from exc
