"""Polymarket adapter tests — all responses mocked via pytest-httpx fixtures."""

from __future__ import annotations

import json

import pytest

from slippage_labs.venues import (
    MarketNotFoundError,
    Polymarket,
    PolymarketMarket,
    Side,
)


# ---- URL parsing (no network) ----

@pytest.mark.parametrize("url", [
    "https://polymarket.com/event/some-slug",
    "https://www.polymarket.com/event/some-slug",
    "https://polymarket.com/market/some-slug?utm=foo",
])
def test_matches_polymarket_urls(url):
    assert Polymarket().matches_url(url)


@pytest.mark.parametrize("url", [
    "https://kalshi.com/markets/foo",
    "KXHIGHNY-26MAY05",
    "not a url",
    "",
])
def test_rejects_non_polymarket_urls(url):
    assert not Polymarket().matches_url(url)


def test_resolve_rejects_unknown_path_shape(httpx_mock):
    # Path doesn't match /event/<slug>.
    with pytest.raises(MarketNotFoundError, match="doesn't match"):
        Polymarket().resolve("https://polymarket.com/profile/foo")


# ---- M4.5 regression: /market/ URLs get a clear "not supported" message ----

def test_market_path_emits_helpful_error(httpx_mock):
    # Pre-fix this silently queried /events?slug=<market-slug> and returned a
    # confusing "no event for slug=…" error.
    with pytest.raises(MarketNotFoundError, match="single-market URLs.*aren't supported"):
        Polymarket().resolve("https://polymarket.com/market/some-individual-market")


# ---- resolve(): fixture-backed event lookup ----

def test_resolve_event_returns_markets(httpx_mock, fixture_loader):
    event_payload = fixture_loader("polymarket_event.json")
    httpx_mock.add_response(
        url="https://gamma-api.polymarket.com/events?slug=highest-temperature-in-hong-kong-on-may-5-2026",
        json=event_payload,
    )
    ev = Polymarket().resolve("https://polymarket.com/event/highest-temperature-in-hong-kong-on-may-5-2026")
    assert ev.venue == "polymarket"
    assert ev.id == "highest-temperature-in-hong-kong-on-may-5-2026"
    assert len(ev.markets) == 2
    m0 = ev.markets[0]
    assert isinstance(m0, PolymarketMarket)
    assert m0.yes_token and m0.no_token
    assert m0.yes_token != m0.no_token
    assert "Hong Kong" in m0.title


def test_resolve_raises_on_empty_event_list(httpx_mock):
    httpx_mock.add_response(
        url="https://gamma-api.polymarket.com/events?slug=does-not-exist",
        json=[],
    )
    with pytest.raises(MarketNotFoundError, match="No Polymarket event"):
        Polymarket().resolve("https://polymarket.com/event/does-not-exist")


# ---- fetch_book() ----

def test_fetch_book_returns_normalized_book(httpx_mock, fixture_loader):
    book_payload = fixture_loader("polymarket_book.json")
    # Use a representative token id from the event fixture.
    event = fixture_loader("polymarket_event.json")
    yes_token = json.loads(event[0]["markets"][0]["clobTokenIds"])[0]

    httpx_mock.add_response(
        url=f"https://clob.polymarket.com/book?token_id={yes_token}",
        json=book_payload,
    )
    market = PolymarketMarket(
        venue="polymarket", id="test", title="Test",
        yes_token=yes_token, no_token="other",
    )
    book = Polymarket().fetch_book(market, Side.YES)
    # Asks should be sorted ascending after normalization.
    assert book.asks == tuple(sorted(book.asks, key=lambda lv: lv.price))
    assert len(book.asks) == len(book_payload["asks"])
    assert all(lv.price > 0 and lv.size > 0 for lv in book.asks)


def test_fetch_book_rejects_wrong_market_type():
    from slippage_labs.venues.base import Market
    other = Market(venue="kalshi", id="X", title="t")
    with pytest.raises(TypeError, match="non-Polymarket market"):
        Polymarket().fetch_book(other, Side.YES)
