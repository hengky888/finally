"""The structured response the model must produce (PLAN.md section 9)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TradeInstruction(BaseModel):
    """A trade the assistant wants executed."""

    ticker: str
    side: Literal["buy", "sell"]
    quantity: float


class WatchlistInstruction(BaseModel):
    """A watchlist addition or removal the assistant wants applied."""

    ticker: str
    action: Literal["add", "remove"]


class AssistantResponse(BaseModel):
    """The whole model reply: prose plus the actions it wants taken."""

    message: str
    trades: list[TradeInstruction] = Field(default_factory=list)
    watchlist_changes: list[WatchlistInstruction] = Field(default_factory=list)
