"""The /api/chat route."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.api.deps import Cache, Conn, Source

from .errors import LLMError
from .service import handle_chat

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    """One message from the user."""

    message: str


@router.post("")
async def send_message(
    body: ChatRequest, request: Request, conn: Conn, cache: Cache, source: Source
) -> dict:
    """Reply to a message, auto-executing any trades or watchlist changes."""
    try:
        return await handle_chat(
            conn, cache, source, request.app.state.settings, body.message
        )
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
