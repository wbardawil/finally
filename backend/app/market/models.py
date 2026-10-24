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
    # First price seen for this ticker since it began being tracked in this
    # process. Defaults to `price` (i.e. this update starts the session).
    session_start_price: float | None = None

    def __post_init__(self) -> None:
        if self.session_start_price is None:
            object.__setattr__(self, "session_start_price", self.price)

    @property
    def change(self) -> float:
        """Absolute price change from previous update."""
        return round(self.price - self.previous_price, 4)

    @property
    def change_percent(self) -> float:
        """Percentage change from previous update."""
        if self.previous_price == 0:
            return 0.0
        return round((self.price - self.previous_price) / self.previous_price * 100, 4)

    @property
    def session_change(self) -> float:
        """Absolute price change since the session-start price."""
        return round(self.price - self.session_start_price, 4)

    @property
    def session_change_percent(self) -> float:
        """Percentage change since the session-start price."""
        if self.session_start_price == 0:
            return 0.0
        return round((self.price - self.session_start_price) / self.session_start_price * 100, 4)

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
            "session_start_price": self.session_start_price,
            "timestamp": self.timestamp,
            "change": self.change,
            "change_percent": self.change_percent,
            "session_change_percent": self.session_change_percent,
            "direction": self.direction,
        }
