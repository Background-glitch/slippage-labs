"""Tests for the threshold solver — pure logic, no I/O."""

import pytest

from slippage_labs import Book, Level, simulate_buy, solve_max_budget


def book(*asks: tuple[float, float], bids: list[tuple[float, float]] | None = None) -> Book:
    return Book.from_levels(
        bids=[Level(p, s) for p, s in (bids or [])],
        asks=[Level(p, s) for p, s in asks],
    )


# ---- regime 1: infeasible against mid ----

def test_infeasible_when_touch_already_above_mid_threshold():
    # mid = 0.45, best_ask = 0.50 → minimum slippage vs mid is +11.11%.
    # Threshold of 5% is infeasible.
    b = book((0.50, 100), bids=[(0.40, 100)])
    res = solve_max_budget(b, threshold_pct=5.0, reference="mid")
    assert res.budget == 0.0
    assert not res.feasible
    assert res.fill.shares == 0


def test_zero_threshold_vs_mid_infeasible_when_spread_exists():
    b = book((0.50, 100), bids=[(0.40, 100)])
    res = solve_max_budget(b, threshold_pct=0.0, reference="mid")
    assert not res.feasible
    assert res.budget == 0.0


# ---- regime 2: book ceiling binds, threshold doesn't ----

def test_book_bound_when_threshold_is_huge():
    # Total notional = 0.40*100 + 0.50*100 = 90. Threshold of 1000% trivially fits.
    b = book((0.40, 100), (0.50, 100))
    res = solve_max_budget(b, threshold_pct=1000.0, reference="touch")
    assert res.book_bound
    assert res.budget == pytest.approx(90.0)
    assert res.fill.filled
    assert res.fill.shares == pytest.approx(200)


def test_zero_threshold_vs_touch_returns_first_level_size():
    # vs touch: avg starts at touch (0% slip) and only grows. With threshold=0,
    # the cap is exactly the size of the best-ask level.
    b = book((0.40, 100), (0.50, 100))
    res = solve_max_budget(b, threshold_pct=0.0, reference="touch")
    assert res.feasible
    assert res.budget == pytest.approx(40.0, abs=0.01)         # 100 shares × $0.40
    assert res.slippage_at_cap_pct == pytest.approx(0.0, abs=0.01)


# ---- regime 3: threshold-bound (binary search) ----

def test_threshold_bound_within_book_vs_mid():
    # Book: $0.40 × 100, $0.60 × 100; mid = 0.395 (with bid at 0.39).
    # Picking threshold=10% → at the cap, avg should be ≤ 1.10 * 0.395 = 0.4345.
    b = book((0.40, 100), (0.60, 100), bids=[(0.39, 100)])
    res = solve_max_budget(b, threshold_pct=10.0, reference="mid")
    assert res.feasible
    assert not res.book_bound
    # Slippage at cap should respect the threshold (within tolerance).
    assert res.slippage_at_cap_pct <= 10.0 + 0.01
    # And going *just past* the cap should exceed it.
    just_past = simulate_buy(b, res.budget + 1.0)
    just_past_slip = just_past.slippage_vs(res.reference_price)
    assert just_past_slip > 10.0


def test_threshold_bound_within_book_vs_touch():
    b = book((0.40, 100), (0.60, 100))
    res = solve_max_budget(b, threshold_pct=10.0, reference="touch")
    # Avg of $0.44 = +10% from $0.40 touch. Solve algebraically:
    # If we take all 100 shares at 0.40 ($40) + x dollars at 0.60:
    #   shares = 100 + x/0.60;  spent = 40 + x;  avg = (40+x)/(100 + x/0.60)
    # avg = 0.44  →  40 + x = 0.44 (100 + x/0.6) = 44 + 0.7333x
    #            →  0.2667x = 4  →  x ≈ $15
    # Cap budget ≈ $55.
    assert res.budget == pytest.approx(55.0, abs=0.5)
    assert res.slippage_at_cap_pct == pytest.approx(10.0, abs=0.05)


# ---- monotonicity & convergence properties ----

def test_solution_is_monotone_in_threshold():
    b = book((0.40, 100), (0.50, 100), (0.60, 100), (0.70, 100))
    last = -1.0
    for t in [0.0, 1.0, 5.0, 25.0, 100.0]:
        cap = solve_max_budget(b, threshold_pct=t, reference="touch").budget
        assert cap >= last
        last = cap


def test_recommended_size_includes_self_reported_slippage():
    # The "$X is the cap, at $X you'd pay Y%" line — verify both are coherent.
    b = book((0.40, 100), (0.50, 100), (0.60, 100))
    res = solve_max_budget(b, threshold_pct=8.0, reference="touch")
    # Cap returned + the slippage at cap — neither None, both internally consistent.
    assert res.budget > 0
    assert res.slippage_at_cap_pct is not None
    # Verify simulate_buy at the recommended budget actually produces that slippage.
    fill = simulate_buy(b, res.budget)
    assert fill.slippage_vs(res.reference_price) == pytest.approx(res.slippage_at_cap_pct)


# ---- edge cases ----

def test_empty_book_returns_zero_budget():
    res = solve_max_budget(book(), threshold_pct=10.0, reference="touch")
    assert res.budget == 0.0
    assert not res.feasible


def test_mid_reference_raises_when_one_side_empty():
    # No bids → no mid available.
    with pytest.raises(ValueError, match="mid"):
        solve_max_budget(book((0.40, 100)), threshold_pct=5.0, reference="mid")


def test_touch_reference_works_when_bids_empty():
    # vs touch should still resolve when there's no bid.
    res = solve_max_budget(book((0.40, 100)), threshold_pct=5.0, reference="touch")
    assert res.feasible
    assert res.reference_price == 0.40


def test_negative_threshold_rejected():
    with pytest.raises(ValueError, match="threshold_pct"):
        solve_max_budget(book((0.40, 100)), threshold_pct=-1.0, reference="touch")


def test_unknown_reference_kind_rejected():
    with pytest.raises(ValueError, match="Unknown reference"):
        solve_max_budget(book((0.40, 100)), threshold_pct=5.0, reference="bogus")  # type: ignore[arg-type]
