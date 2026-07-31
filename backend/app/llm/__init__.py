"""LLM chat integration: structured outputs, auto-execution and /api/chat."""

from .errors import LLMError
from .router import router as chat_router
from .schema import AssistantResponse, TradeInstruction, WatchlistInstruction

__all__ = [
    "AssistantResponse",
    "LLMError",
    "TradeInstruction",
    "WatchlistInstruction",
    "chat_router",
]
