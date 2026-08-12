"""Thread-safe in-memory price cache."""

from __future__ import annotations

import time
from dataclasses import replace
from threading import Lock

from .models import PriceUpdate


class PriceCache:
    """Thread-safe in-memory cache of the latest price for each ticker.

    Writers: SimulatorDataSource or MassiveDataSource (one at a time).
    Readers: SSE streaming endpoint, portfolio valuation, trade execution.
    """

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self._references: dict[str, float] = {}
        self._lock = Lock()
        self._version: int = 0  # Monotonically increasing; see `version`

    def update(self, ticker: str, price: float, timestamp: float | None = None) -> PriceUpdate:
        """Record a new price for a ticker. Returns the created PriceUpdate.

        Automatically computes direction and change from the previous price.
        If this is the first update for the ticker, previous_price == price (direction='flat').

        The first price seen for a ticker also becomes its reference price unless
        one was already set via `set_reference()`, so `daily_change_percent` is
        measured from the session open.
        """
        with self._lock:
            ts = time.time() if timestamp is None else timestamp
            prev = self._prices.get(ticker)
            previous_price = prev.price if prev else price
            rounded = round(price, 2)

            reference = self._references.setdefault(ticker, rounded)

            update = PriceUpdate(
                ticker=ticker,
                price=rounded,
                previous_price=round(previous_price, 2),
                timestamp=ts,
                reference_price=reference,
            )
            self._prices[ticker] = update
            self._version += 1
            return update

    def set_reference(self, ticker: str, price: float) -> None:
        """Set the reference price `daily_change_percent` is measured against.

        Call before the first `update()` for a ticker to override the default
        (session-open) reference — e.g. with the previous session's close.
        Rewrites the current PriceUpdate if one already exists.
        """
        with self._lock:
            self._references[ticker] = round(price, 2)
            current = self._prices.get(ticker)
            if current is not None:
                self._prices[ticker] = replace(current, reference_price=round(price, 2))
                self._version += 1

    def get(self, ticker: str) -> PriceUpdate | None:
        """Get the latest price for a single ticker, or None if unknown."""
        with self._lock:
            return self._prices.get(ticker)

    def get_all(self) -> dict[str, PriceUpdate]:
        """Snapshot of all current prices. Returns a shallow copy."""
        with self._lock:
            return dict(self._prices)

    def get_price(self, ticker: str) -> float | None:
        """Convenience: get just the price float, or None."""
        update = self.get(ticker)
        return update.price if update else None

    def remove(self, ticker: str) -> None:
        """Remove a ticker from the cache (e.g., when removed from watchlist).

        Bumps the version so a removal is observable to version-based consumers;
        without this a dropped ticker would be invisible until some other ticker
        happened to tick.
        """
        with self._lock:
            if self._prices.pop(ticker, None) is not None:
                self._version += 1
            self._references.pop(ticker, None)

    @property
    def version(self) -> int:
        """Monotonic counter bumped on every mutation (update, reference, remove).

        Lets a consumer detect "has anything changed since I last looked?" without
        diffing the whole snapshot. The SSE stream no longer gates on this — it
        emits every tick by design — but the counter remains correct for any
        consumer that wants change detection.
        """
        with self._lock:
            return self._version

    def __len__(self) -> int:
        with self._lock:
            return len(self._prices)

    def __contains__(self, ticker: str) -> bool:
        with self._lock:
            return ticker in self._prices
