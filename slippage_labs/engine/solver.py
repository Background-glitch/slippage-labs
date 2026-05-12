"""Find the largest order size that stays under a slippage threshold.

`avg_price(B)` is a continuous, non-decreasing function of budget B (the walker
takes asks lowest-first), so the feasible set `{B : slippage(B) ≤ threshold}`
is an interval `[0, B*]`. We binary-search for B*.

Three regimes worth naming:

1. Infeasible — even the smallest buy slips beyond the threshold. Only
   possible when `reference="mid"`, because best_ask ≥ mid always, so any buy
   slips by at least `(best_ask - mid)/mid` against mid. We return $0.
2. Book-bound — sweeping the entire ask side still stays under the threshold.
   The cap is the total ask notional; the threshold isn't binding.
3. Threshold-bound — somewhere inside the book, taking the next level would
   tip avg_price past the threshold. Binary search lands on the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from slippage_labs.engine.book import Book
from slippage_labs.engine.walker import FillResult, simulate_buy

ReferenceKind = Literal["mid", "touch"]


@dataclass(frozen=True)
class MaxBudgetResult:
    """Outcome of a max-budget-under-threshold solve."""
    budget: float                 # the cap (USD)
    fill: FillResult              # walker's output at exactly that budget
    threshold_pct: float          # what the user asked for
    reference_price: float        # the price slippage was measured against
    reference_kind: ReferenceKind # "mid" or "touch"
    book_bound: bool              # True iff the cap is the book ceiling, not the threshold

    @property
    def slippage_at_cap_pct(self) -> float | None:
        """Realized slippage at the recommended budget — what to show the user."""
        return self.fill.slippage_vs(self.reference_price)

    @property
    def feasible(self) -> bool:
        """False iff even the smallest buy already exceeds the threshold."""
        return self.fill.shares > 0


def _reference_price(book: Book, kind: ReferenceKind) -> float:
    if kind == "mid":
        if book.mid is None:
            raise ValueError(
                "Cannot use reference='mid' on a book missing one side. "
                "Pass reference='touch' instead."
            )
        return book.mid
    if kind == "touch":
        if book.best_ask is None:
            raise ValueError("Empty ask side — no touch price.")
        return book.best_ask
    raise ValueError(f"Unknown reference kind {kind!r}")


def solve_max_budget(
    book: Book,
    threshold_pct: float,
    reference: ReferenceKind = "mid",
    *,
    tolerance_usd: float = 0.005,
    max_iter: int = 60,
) -> MaxBudgetResult:
    """Return the largest budget whose avg fill price stays within `threshold_pct`.

    Slippage is measured as `(avg_price - reference) / reference * 100`. With
    `reference="mid"` the answer can be infeasible (touch already over threshold)
    and we return budget=0. With `reference="touch"` the answer is always at
    least the size of the best-ask level, since any buy at the touch has 0% slip.
    """
    if threshold_pct < 0:
        raise ValueError(f"threshold_pct must be ≥ 0; got {threshold_pct}")

    # Empty ask side → nothing can be filled. Skip the reference lookup since
    # there's no price to measure against, and reference_price would be undefined.
    if not book.asks:
        return MaxBudgetResult(
            budget=0.0,
            fill=simulate_buy(book, 0.0),
            threshold_pct=threshold_pct,
            reference_price=float("nan"),
            reference_kind=reference,
            book_bound=False,
        )

    ref_price = _reference_price(book, reference)

    # Regime 1: infeasible. Even buying $0.01 worth at the touch slips by
    # (best_ask - ref)/ref. If that's already over threshold, no budget works.
    min_slip_pct = (book.best_ask - ref_price) / ref_price * 100
    if min_slip_pct > threshold_pct:
        return MaxBudgetResult(
            budget=0.0,
            fill=simulate_buy(book, 0.0),
            threshold_pct=threshold_pct,
            reference_price=ref_price,
            reference_kind=reference,
            book_bound=False,
        )

    # Zero-notional asks (every level has size 0): no liquidity to take. Report
    # as book-bound rather than infeasible — the threshold isn't the problem.
    ceiling = book.total_ask_notional
    if ceiling <= 0:
        return MaxBudgetResult(
            budget=0.0,
            fill=simulate_buy(book, 0.0),
            threshold_pct=threshold_pct,
            reference_price=ref_price,
            reference_kind=reference,
            book_bound=True,
        )

    # Regime 2: full sweep stays under threshold → book is the binding constraint.
    full = simulate_buy(book, ceiling)
    full_slip = full.slippage_vs(ref_price)
    if full_slip is not None and full_slip <= threshold_pct:
        return MaxBudgetResult(
            budget=ceiling,
            fill=full,
            threshold_pct=threshold_pct,
            reference_price=ref_price,
            reference_kind=reference,
            book_bound=True,
        )

    # Regime 3: binary search between (low=feasible, high=infeasible).
    low, high = 0.0, ceiling
    for _ in range(max_iter):
        if high - low < tolerance_usd:
            break
        mid_b = (low + high) / 2
        slip = simulate_buy(book, mid_b).slippage_vs(ref_price)
        if slip is None or slip <= threshold_pct:
            low = mid_b
        else:
            high = mid_b

    return MaxBudgetResult(
        budget=low,
        fill=simulate_buy(book, low),
        threshold_pct=threshold_pct,
        reference_price=ref_price,
        reference_kind=reference,
        book_bound=False,
    )
