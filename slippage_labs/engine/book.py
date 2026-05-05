"""Order-book primitives. Pure data — no venue knowledge."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Level:
    """A single price level on one side of the book.

    Prediction-market shares pay $1 at expiry, so price must satisfy 0 < price ≤ 1.
    Size is non-negative (a 0-size level is a no-op but tolerated).

    Validation is here rather than in the walker so corrupt API data fails loudly
    at parse time, not silently with weird fills (e.g. a price=0 level would have
    looked like 'free shares' to the walker).
    """
    price: float
    size: float

    def __post_init__(self) -> None:
        if math.isnan(self.price) or math.isinf(self.price) or self.price <= 0 or self.price > 1:
            raise ValueError(
                f"Level.price must be in (0, 1] for a prediction-market share; got {self.price!r}"
            )
        if math.isnan(self.size) or math.isinf(self.size) or self.size < 0:
            raise ValueError(f"Level.size must be a finite, non-negative number; got {self.size!r}")


@dataclass(frozen=True)
class Book:
    """Snapshot of an order book, normalized so best prices come first.

    `bids` are sorted highest-price first (best bid at index 0).
    `asks` are sorted lowest-price first  (best ask at index 0).
    """
    bids: tuple[Level, ...]
    asks: tuple[Level, ...]

    @classmethod
    def from_levels(cls, bids: list[Level], asks: list[Level]) -> "Book":
        """Construct, sorting both sides into the canonical orientation."""
        return cls(
            bids=tuple(sorted(bids, key=lambda lv: -lv.price)),
            asks=tuple(sorted(asks, key=lambda lv: lv.price)),
        )

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def mid(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2

    @property
    def total_ask_notional(self) -> float:
        """Maximum USD that can ever be filled by sweeping the entire ask side."""
        return sum(lv.price * lv.size for lv in self.asks)
