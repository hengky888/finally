"""Data models for market data."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Immutable snapshot of a single ticker's price at a point in time."""

    ticker: str
    price: float
    previous_price: float
    timestamp: float = field(default_factory=time.time)  # Unix seconds
    # Session-open (simulator) or previous close (Massive). `daily_change_percent`
    # is measured against this. None until a reference is established.
    reference_price: float | None = None

    @property
    def change(self) -> float:
        """Absolute price change from previous update."""
        return round(self.price - self.previous_price, 4)

    @property
    def daily_change(self) -> float | None:
        """Absolute change from the session reference price, or None if unset."""
        if self.reference_price is None:
            return None
        return round(self.price - self.reference_price, 4)

    @property
    def daily_change_percent(self) -> float | None:
        """Percentage change from the session reference price, or None if unset.

        This is the figure the watchlist's "daily change %" column needs — unlike
        `change_percent`, it does not depend on tick timing or connection age.
        """
        if not self.reference_price:
            return None
        return round((self.price - self.reference_price) / self.reference_price * 100, 4)

    @property
    def change_percent(self) -> float:
        """Percentage change from previous update."""
        if self.previous_price == 0:
            return 0.0
        return round((self.price - self.previous_price) / self.previous_price * 100, 4)

    @property
    def direction(self) -> str:
        """'up', 'down', or 'flat'."""
        if self.price > self.previous_price:
            return "up"
        elif self.price < self.previous_price:
            return "down"
        return "flat"

    def to_dict(self) -> dict:
        """Serialize for JSON / SSE transmission."""
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "timestamp": self.timestamp,
            "change": self.change,
            "change_percent": self.change_percent,
            "direction": self.direction,
            "reference_price": self.reference_price,
            "daily_change": self.daily_change,
            "daily_change_percent": self.daily_change_percent,
        }
