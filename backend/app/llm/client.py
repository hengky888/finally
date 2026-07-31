"""The LiteLLM call: OpenRouter with Cerebras as the inference provider."""

from __future__ import annotations

import asyncio

from litellm import completion

from app.config import Settings

from .errors import LLMError
from .mock import mock_completion
from .schema import AssistantResponse

MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}

MISSING_KEY = (
    "Chat is unavailable: OPENROUTER_API_KEY is not set. Add it to .env, "
    "or run with LLM_MOCK=true for canned responses."
)


async def complete(messages: list[dict], settings: Settings) -> str:
    """Return the raw JSON content of the model's reply.

    Runs the blocking LiteLLM call in a worker thread so the event loop keeps
    serving the price stream while the model thinks.
    """
    if settings.llm_mock:
        return mock_completion(messages)
    if not settings.openrouter_api_key:
        raise LLMError(MISSING_KEY)

    try:
        response = await asyncio.to_thread(
            completion,
            model=MODEL,
            messages=messages,
            response_format=AssistantResponse,
            reasoning_effort="low",
            extra_body=EXTRA_BODY,
        )
    except Exception as exc:
        raise LLMError(f"The assistant is unreachable: {exc}") from exc
    return response.choices[0].message.content
