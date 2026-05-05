"""Kalshi adapter.

Quirk worth remembering: Kalshi's `/markets/{ticker}/orderbook` endpoint returns
RESTING BIDS on each side (`yes_dollars`, `no_dollars`), not asks. To buy YES at
market we cross the NO bids — a NO bid at $0.98 is an implied YES ask at $0.02.
We synthesize the ask side here so the engine sees a normal Book.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from slippage_labs.engine.book import Book, Level
from slippage_labs.venues._http import get_client
from slippage_labs.venues.base import (
    Event,
    Market,
    MarketNotFoundError,
    Side,
    Venue,
    VenueError,
)

KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"

# Kalshi event tickers look like KXHIGHNY-26MAY05 (uppercase letters/digits with one or more dashes).
_TICKER_RE = re.compile(r"\b([A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+)\b")


@dataclass(frozen=True)
class KalshiMarket(Market):
    """Kalshi sub-market — `id` is the market ticker used to query the orderbook."""


class Kalshi(Venue):
    name = "kalshi"

    def matches_url(self, url: str) -> bool:
        try:
            host = (urlparse(url).hostname or "").lower()
        except ValueError:
            return False
        if host.endswith("kalshi.com"):
            return True
        # Also accept a bare event ticker like "KXHIGHNY-26MAY05" so users can paste it directly.
        return bool(_TICKER_RE.fullmatch(url.strip()))

    def resolve(self, url: str) -> Event:
        ticker = _event_ticker_from(url)
        client = get_client()
        r = client.get(f"{KALSHI_API}/events/{ticker}")
        if r.status_code == 404:
            raise MarketNotFoundError(_describe_404(ticker))
        r.raise_for_status()
        data = r.json()
        raw_markets = data.get("markets") or (data.get("event") or {}).get("markets") or []
        if not raw_markets:
            raise MarketNotFoundError(f"Kalshi event {ticker!r} has no markets")
        title = (data.get("event") or {}).get("title") or data.get("title") or ticker
        return Event(
            venue=self.name,
            id=ticker,
            title=title,
            markets=tuple(_parse_market(m) for m in raw_markets),
            is_single_market=False,
        )

    def fetch_book(self, market: Market, side: Side) -> Book:
        if not isinstance(market, KalshiMarket):
            raise TypeError(f"Kalshi.fetch_book got non-Kalshi market: {market!r}")
        client = get_client()
        r = client.get(f"{KALSHI_API}/markets/{market.id}/orderbook")
        r.raise_for_status()
        body = r.json()
        # Only accept orderbook_fp (full-precision dollars). The legacy `orderbook`
        # field returns prices in CENTS, which our adapter would silently misinterpret
        # as dollars — refuse rather than guess wrong.
        raw = body.get("orderbook_fp")
        if raw is None:
            raise VenueError(
                f"Kalshi orderbook for {market.id} missing 'orderbook_fp'; "
                f"refusing to use cents-encoded fallback."
            )
        try:
            yes_bids = _to_levels(raw.get("yes_dollars") or [])
            no_bids = _to_levels(raw.get("no_dollars") or [])
        except (KeyError, TypeError, ValueError) as e:
            raise VenueError(f"Kalshi returned invalid orderbook for {market.id}: {e}") from e

        # To buy `side`, our asks are derived from the OPPOSITE side's bids:
        # ask_price = 1 - opposite_bid_price (each contract pays $1 at expiry).
        if side is Side.YES:
            own_bids, cross_bids = yes_bids, no_bids
        else:
            own_bids, cross_bids = no_bids, yes_bids
        try:
            asks = [Level(round(1 - lv.price, 4), lv.size) for lv in cross_bids]
        except ValueError as e:
            raise VenueError(f"Kalshi orderbook contains invalid level for {market.id}: {e}") from e
        return Book.from_levels(own_bids, asks)


def _event_ticker_from(url: str) -> str:
    """Pull a Kalshi event ticker out of the URL (or accept a bare ticker)."""
    candidate = url.strip()
    if _TICKER_RE.fullmatch(candidate):
        return candidate
    parsed = urlparse(url)
    haystack = " ".join(filter(None, (parsed.path, parsed.query, parsed.fragment)))
    m = _TICKER_RE.search(haystack)
    if not m:
        raise MarketNotFoundError(
            f"Could not find a Kalshi event ticker in URL {url!r}. "
            "Try pasting the ticker directly (e.g. KXHIGHNY-26MAY05)."
        )
    return m.group(1)


def _describe_404(ticker: str) -> str:
    """Friendlier error than 'HTTP 404' — guess if user pasted a market ticker."""
    parts = ticker.split("-")
    base = (
        f"Kalshi has no event with ticker {ticker!r}. "
        "Double-check the ticker on kalshi.com."
    )
    # Event tickers are typically 2 segments (KXHIGHNY-26MAY05);
    # market tickers append a third (KXHIGHNY-26MAY05-T77, KXHIGHNY-26MAY05-B77).
    if len(parts) >= 3:
        event_guess = "-".join(parts[:2])
        return (
            base + f" If {ticker!r} is a market ticker, try just the event part: "
            f"{event_guess!r}."
        )
    return base


def _to_levels(arr: list) -> list[Level]:
    return [Level(float(p), float(s)) for p, s in arr]


def _parse_market(m: dict) -> KalshiMarket:
    return KalshiMarket(
        venue="kalshi",
        id=m["ticker"],
        title=(m.get("yes_sub_title")
               or m.get("subtitle")
               or m.get("title")
               or m["ticker"]),
    )
