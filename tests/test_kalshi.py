"""Kalshi adapter tests — including the bid→ask synthesis quirk."""

from __future__ import annotations

import pytest

from slippage_labs.venues import Kalshi, KalshiMarket, MarketNotFoundError, Side


# ---- URL / ticker recognition ----

@pytest.mark.parametrize("url", [
    "https://kalshi.com/markets/kxhighny/highest-temperature-in-nyc",
    "https://kalshi.com/events/KXHIGHNY-26MAY05",
    "KXHIGHNY-26MAY05",   # bare ticker pasted directly
])
def test_matches_kalshi_inputs(url):
    assert Kalshi().matches_url(url)


@pytest.mark.parametrize("url", [
    "https://polymarket.com/event/foo",
    "highest-temperature",   # no ticker pattern
    "",
])
def test_rejects_non_kalshi_inputs(url):
    assert not Kalshi().matches_url(url)


def test_resolve_extracts_ticker_from_url(httpx_mock, fixture_loader):
    payload = fixture_loader("kalshi_event.json")
    httpx_mock.add_response(
        url="https://api.elections.kalshi.com/trade-api/v2/events/KXHIGHNY-26MAY05",
        json=payload,
    )
    ev = Kalshi().resolve("https://kalshi.com/events/KXHIGHNY-26MAY05")
    assert ev.id == "KXHIGHNY-26MAY05"
    assert len(ev.markets) == 2
    assert isinstance(ev.markets[0], KalshiMarket)
    assert ev.markets[0].id.startswith("KXHIGHNY-")


def test_resolve_accepts_bare_ticker(httpx_mock, fixture_loader):
    httpx_mock.add_response(
        url="https://api.elections.kalshi.com/trade-api/v2/events/KXHIGHNY-26MAY05",
        json=fixture_loader("kalshi_event.json"),
    )
    ev = Kalshi().resolve("KXHIGHNY-26MAY05")
    assert ev.id == "KXHIGHNY-26MAY05"


def test_resolve_raises_when_no_ticker_in_url():
    with pytest.raises(MarketNotFoundError, match="Could not find a Kalshi event ticker"):
        Kalshi().resolve("https://kalshi.com/no/ticker/here")


# ---- M4.5 regression: 404 includes event-vs-market hint ----

def test_404_on_market_ticker_suggests_event_part(httpx_mock):
    # 3-segment ticker is probably a market ticker — error should suggest stripping the last part.
    httpx_mock.add_response(
        url="https://api.elections.kalshi.com/trade-api/v2/events/KXHIGHNY-26MAY05-T77",
        status_code=404,
    )
    with pytest.raises(MarketNotFoundError) as exc:
        Kalshi().resolve("KXHIGHNY-26MAY05-T77")
    msg = str(exc.value)
    assert "market ticker" in msg
    assert "'KXHIGHNY-26MAY05'" in msg     # the suggested event-part guess


def test_404_on_event_shaped_ticker_no_strip_hint(httpx_mock):
    # 2-segment ticker looks like an event already; no "try just the event part" hint.
    httpx_mock.add_response(
        url="https://api.elections.kalshi.com/trade-api/v2/events/KXFOO-99XXX",
        status_code=404,
    )
    with pytest.raises(MarketNotFoundError) as exc:
        Kalshi().resolve("KXFOO-99XXX")
    assert "no event with ticker" in str(exc.value)
    assert "market ticker" not in str(exc.value)


# ---- fetch_book(): the bid→ask synthesis quirk ----

def test_fetch_book_yes_synthesizes_asks_from_no_bids(httpx_mock, fixture_loader):
    payload = fixture_loader("kalshi_book.json")
    raw = payload["orderbook_fp"]
    no_bids = raw["no_dollars"]

    httpx_mock.add_response(
        url="https://api.elections.kalshi.com/trade-api/v2/markets/KXHIGHNY-26MAY05-T77/orderbook",
        json=payload,
    )
    market = KalshiMarket(venue="kalshi", id="KXHIGHNY-26MAY05-T77", title="t")
    book = Kalshi().fetch_book(market, Side.YES)

    # Every YES ask should equal 1 - some NO bid price.
    assert len(book.asks) == len(no_bids)
    no_prices = {round(1 - float(p), 4) for p, _ in no_bids}
    book_ask_prices = {lv.price for lv in book.asks}
    assert book_ask_prices == no_prices

    # Asks sorted ascending; the cheapest YES ask = 1 - highest NO bid.
    highest_no_bid = max(float(p) for p, _ in no_bids)
    assert book.best_ask == pytest.approx(round(1 - highest_no_bid, 4))


def test_fetch_book_no_uses_yes_bids_for_asks(httpx_mock, fixture_loader):
    payload = fixture_loader("kalshi_book.json")
    yes_bids = payload["orderbook_fp"]["yes_dollars"]

    httpx_mock.add_response(
        url="https://api.elections.kalshi.com/trade-api/v2/markets/KXHIGHNY-26MAY05-T77/orderbook",
        json=payload,
    )
    market = KalshiMarket(venue="kalshi", id="KXHIGHNY-26MAY05-T77", title="t")
    book = Kalshi().fetch_book(market, Side.NO)

    assert len(book.asks) == len(yes_bids)
    assert book.best_ask == pytest.approx(round(1 - max(float(p) for p, _ in yes_bids), 4))
