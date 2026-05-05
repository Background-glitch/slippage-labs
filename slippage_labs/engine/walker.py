"""Simulate a market BUY by walking the ask side of an order book."""

from __future__ import annotations

import math
from dataclasses import dataclass

from slippage_labs.engine.book import Book, Level


@dataclass(frozen=True)
class Fill:
    """One level's worth of a simulated fill."""
    level: Level
    shares_taken: float
    cost: float


@dataclass(frozen=True)
class FillResult:
    """Outcome of a simulated market buy. Leftover budget is treated as cancelled."""
    fills: tuple[Fill, ...]
    shares: float
    spent: float
    remaining: float       # USD that couldn't be filled (book exhausted)
    avg_price: float       # NaN if zero shares filled
    filled: bool           # True iff the full budget was consumed

    def slippage_vs(self, reference_price: float | None) -> float | None:
        """Return percent slippage of avg_price vs the reference, or None."""
        if reference_price is None or reference_price <= 0 or math.isnan(self.avg_price):
            return None
        return (self.avg_price - reference_price) / reference_price * 100


def simulate_buy(book: Book, budget_usd: float) -> FillResult:
    """Walk asks lowest-first, spending USD until budget is exhausted or book runs out.

    Cancellation semantics: any unfilled budget is reported as `remaining` and
    is NOT placed as a resting bid — the simulator models a marketable IOC.
    """
    if math.isnan(budget_usd) or math.isinf(budget_usd):
        raise ValueError(f"budget_usd must be a finite number; got {budget_usd!r}")
    if budget_usd <= 0:
        return FillResult(fills=(), shares=0.0, spent=0.0, remaining=budget_usd,
                          avg_price=float("nan"), filled=False)

    remaining = float(budget_usd)
    shares = 0.0
    fills: list[Fill] = []

    for lv in book.asks:
        if remaining <= 0:
            break
        level_cost = lv.price * lv.size
        if level_cost <= remaining:
            shares_taken, cost = lv.size, level_cost
        else:
            shares_taken, cost = remaining / lv.price, remaining
        shares += shares_taken
        remaining -= cost
        fills.append(Fill(level=lv, shares_taken=shares_taken, cost=cost))

    spent = budget_usd - remaining
    avg = (spent / shares) if shares > 0 else float("nan")
    return FillResult(
        fills=tuple(fills),
        shares=shares,
        spent=spent,
        remaining=remaining,
        avg_price=avg,
        filled=remaining <= 1e-9,
    )
