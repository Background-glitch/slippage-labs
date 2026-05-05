"""Unit tests for the slippage walker.

Engine code is pure — no I/O, no fixtures from network. Just hand-crafted books.
"""

import math

import pytest

from slippage_labs import Book, Level, simulate_buy


def book(*asks: tuple[float, float], bids: list[tuple[float, float]] | None = None) -> Book:
    """Compact constructor: book((0.40, 100), (0.41, 50)) → Book with two ask levels."""
    return Book.from_levels(
        bids=[Level(p, s) for p, s in (bids or [])],
        asks=[Level(p, s) for p, s in asks],
    )


# ---- core fill behavior ----

def test_fills_within_first_level_partial():
    # 100 shares offered at $0.40 = $40 of liquidity. Buy $10 → 25 shares, no slippage.
    b = book((0.40, 100))
    r = simulate_buy(b, budget_usd=10.0)
    assert r.filled
    assert r.shares == pytest.approx(25.0)
    assert r.spent == pytest.approx(10.0)
    assert r.remaining == pytest.approx(0.0)
    assert r.avg_price == pytest.approx(0.40)
    assert len(r.fills) == 1


def test_fills_walk_multiple_levels():
    # L0: 100 shares @ $0.40 = $40 → take all.  Remaining $20.
    # L1: $20 / $0.50 = 40 shares taken.  Total 140 shares for $60.
    b = book((0.40, 100), (0.50, 100))
    r = simulate_buy(b, budget_usd=60.0)
    assert r.filled
    assert r.shares == pytest.approx(140.0)
    assert r.spent == pytest.approx(60.0)
    assert r.avg_price == pytest.approx(60.0 / 140.0)
    assert len(r.fills) == 2


def test_partial_fill_when_book_exhausts():
    # Total ask depth = 100 * 0.40 = $40. Try to buy $100.
    b = book((0.40, 100))
    r = simulate_buy(b, budget_usd=100.0)
    assert not r.filled
    assert r.shares == pytest.approx(100)
    assert r.spent == pytest.approx(40.0)
    assert r.remaining == pytest.approx(60.0)
    assert r.avg_price == pytest.approx(0.40)


def test_empty_book_returns_zero_fill():
    b = book()
    r = simulate_buy(b, budget_usd=500.0)
    assert not r.filled
    assert r.shares == 0.0
    assert r.spent == 0.0
    assert r.remaining == pytest.approx(500.0)
    assert math.isnan(r.avg_price)
    assert r.fills == ()


def test_zero_budget_is_noop():
    b = book((0.40, 100))
    r = simulate_buy(b, budget_usd=0.0)
    assert not r.filled                  # nothing was filled
    assert r.shares == 0.0
    assert r.spent == 0.0
    assert math.isnan(r.avg_price)


def test_negative_budget_is_noop():
    b = book((0.40, 100))
    r = simulate_buy(b, budget_usd=-50.0)
    assert r.shares == 0.0
    assert r.spent == 0.0


# ---- M4.5 regression: reject non-finite budget ----

def test_inf_budget_rejected():
    import math
    with pytest.raises(ValueError, match="finite"):
        simulate_buy(book((0.40, 100)), budget_usd=math.inf)


def test_nan_budget_rejected():
    import math
    with pytest.raises(ValueError, match="finite"):
        simulate_buy(book((0.40, 100)), budget_usd=math.nan)


# ---- M4.5 regression: invalid Level prices/sizes are rejected ----

def test_zero_price_level_rejected():
    # Pre-fix this would have given the walker "free shares" — see slippage-labs#bug-1.
    with pytest.raises(ValueError, match="price"):
        Level(0.0, 100)


def test_negative_price_level_rejected():
    with pytest.raises(ValueError, match="price"):
        Level(-0.10, 100)


def test_price_above_one_rejected():
    with pytest.raises(ValueError, match="price"):
        Level(1.5, 100)


def test_nan_price_rejected():
    import math
    with pytest.raises(ValueError, match="price"):
        Level(math.nan, 100)


def test_negative_size_rejected():
    with pytest.raises(ValueError, match="size"):
        Level(0.40, -10)


def test_nan_size_rejected():
    import math
    with pytest.raises(ValueError, match="size"):
        Level(0.40, math.nan)


def test_inf_size_rejected():
    import math
    with pytest.raises(ValueError, match="size"):
        Level(0.40, math.inf)


def test_price_at_one_allowed():
    # Resolved markets can quote 1.0 — not common in live books but valid.
    lv = Level(1.0, 50)
    assert lv.price == 1.0


def test_zero_size_allowed():
    # Zero-size level is a no-op but tolerated (some venues emit them transiently).
    lv = Level(0.40, 0)
    assert lv.size == 0


# ---- ordering invariants ----

def test_book_normalizes_ask_ordering():
    # Pass asks out of order — Book.from_levels must sort them.
    b = Book.from_levels(
        bids=[Level(0.39, 50), Level(0.38, 100)],   # bids passed low→high
        asks=[Level(0.50, 100), Level(0.40, 100)],  # asks passed high→low
    )
    assert [lv.price for lv in b.asks] == [0.40, 0.50]
    assert [lv.price for lv in b.bids] == [0.39, 0.38]
    assert b.best_ask == 0.40
    assert b.best_bid == 0.39
    assert b.mid == pytest.approx(0.395)


def test_walker_relies_on_normalization():
    # If asks weren't sorted, walking would skip cheap liquidity. Verify a
    # caller-supplied jumbled list still produces the cheapest-first fill.
    b = Book.from_levels(
        bids=[],
        asks=[Level(0.60, 100), Level(0.40, 50), Level(0.50, 100)],
    )
    r = simulate_buy(b, budget_usd=20.0)
    assert r.fills[0].level.price == 0.40   # cheapest taken first


# ---- slippage helper ----

def test_slippage_vs_reference():
    # avg = 60/140 ≈ 0.4286 — about 7.14% over the 0.40 best ask.
    b = book((0.40, 100), (0.50, 100))
    r = simulate_buy(b, budget_usd=60.0)
    assert r.slippage_vs(0.40) == pytest.approx((60 / 140 - 0.40) / 0.40 * 100)
    assert r.slippage_vs(60 / 140) == pytest.approx(0.0)
    assert r.slippage_vs(None) is None
    assert r.slippage_vs(0.0) is None                   # reject divide-by-zero


def test_slippage_is_nan_safe_when_unfilled():
    b = book()
    r = simulate_buy(b, budget_usd=100.0)
    assert r.slippage_vs(0.50) is None


# ---- book convenience properties ----

def test_total_ask_notional():
    b = book((0.40, 100), (0.50, 100), (0.60, 100))
    assert b.total_ask_notional == pytest.approx(40 + 50 + 60)


def test_mid_is_none_when_one_side_empty():
    assert book((0.40, 100)).mid is None
    assert book(bids=[(0.40, 100)]).mid is None
