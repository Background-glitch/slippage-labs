"""Tests for the URL → Venue dispatcher."""

import pytest

from slippage_labs import UnsupportedURLError, venue_for
from slippage_labs.venues import Kalshi, Polymarket


@pytest.mark.parametrize("url, expected", [
    ("https://polymarket.com/event/foo", "polymarket"),
    ("https://www.polymarket.com/market/bar", "polymarket"),
    ("https://kalshi.com/markets/kxhighny", "kalshi"),
    ("KXHIGHNY-26MAY05", "kalshi"),
])
def test_dispatches_to_correct_venue(url, expected):
    assert venue_for(url).name == expected


def test_unknown_url_raises():
    with pytest.raises(UnsupportedURLError):
        venue_for("https://example.com/foo")


def test_dispatch_respects_custom_venue_list():
    # Force only Polymarket — a Kalshi URL should be unsupported.
    with pytest.raises(UnsupportedURLError):
        venue_for("KXHIGHNY-26MAY05", venues=(Polymarket(),))
    # And vice versa.
    with pytest.raises(UnsupportedURLError):
        venue_for("https://polymarket.com/event/x", venues=(Kalshi(),))
