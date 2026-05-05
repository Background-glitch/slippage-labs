"""Polymarket adapter (Gamma API for events, CLOB API for order books)."""

from __future__ import annotations

import json
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

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

# v0.1 only supports event URLs. Single-market URLs (/market/<slug>) need a
# different Gamma endpoint (/markets?slug=…) — punt to v0.2.
_EVENT_PATH_RE = re.compile(r"^/event/([^/?#]+)")
_MARKET_PATH_RE = re.compile(r"^/market/([^/?#]+)")


@dataclass(frozen=True)
class PolymarketMarket(Market):
    """Polymarket sub-market — carries the YES/NO ERC-1155 token IDs needed to fetch books."""
    yes_token: str = ""
    no_token: str = ""

    def token_for(self, side: Side) -> str:
        return self.yes_token if side is Side.YES else self.no_token


class Polymarket(Venue):
    name = "polymarket"

    def matches_url(self, url: str) -> bool:
        try:
            host = urlparse(url).hostname or ""
        except ValueError:
            return False
        return host.endswith("polymarket.com")

    def resolve(self, url: str) -> Event:
        slug = _slug_from_url(url)
        client = get_client()
        r = client.get(f"{GAMMA_API}/events", params={"slug": slug})
        r.raise_for_status()
        events = r.json()
        if not events:
            raise MarketNotFoundError(f"No Polymarket event for slug={slug!r}")
        ev = events[0]
        markets = tuple(_parse_market(m) for m in ev.get("markets", []))
        return Event(
            venue=self.name,
            id=slug,
            title=ev.get("title", slug),
            markets=markets,
            is_single_market=False,
        )

    def fetch_book(self, market: Market, side: Side) -> Book:
        if not isinstance(market, PolymarketMarket):
            raise TypeError(f"Polymarket.fetch_book got non-Polymarket market: {market!r}")
        token_id = market.token_for(side)
        client = get_client()
        r = client.get(f"{CLOB_API}/book", params={"token_id": token_id})
        r.raise_for_status()
        raw = r.json()
        try:
            bids = [Level(float(b["price"]), float(b["size"])) for b in raw.get("bids", [])]
            asks = [Level(float(a["price"]), float(a["size"])) for a in raw.get("asks", [])]
        except (KeyError, TypeError, ValueError) as e:
            raise VenueError(
                f"Polymarket returned invalid book data for token {token_id}: {e}"
            ) from e
        return Book.from_levels(bids, asks)


def _slug_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or ""
    if _MARKET_PATH_RE.match(path):
        raise MarketNotFoundError(
            f"Polymarket single-market URLs ({path}) aren't supported in v0.1. "
            f"Open the parent event in your browser and paste that URL instead "
            f"(it will look like https://polymarket.com/event/<slug>)."
        )
    m = _EVENT_PATH_RE.match(path)
    if not m:
        raise MarketNotFoundError(
            f"Polymarket URL {url!r} doesn't match /event/<slug>."
        )
    return m.group(1)


def _parse_market(m: dict) -> PolymarketMarket:
    """Translate one entry from Gamma's `markets` array into a PolymarketMarket."""
    outcomes = json.loads(m["outcomes"])           # e.g. ["Yes", "No"]
    token_ids = json.loads(m["clobTokenIds"])      # aligned with outcomes
    yes_idx = outcomes.index("Yes")
    no_idx = outcomes.index("No")
    return PolymarketMarket(
        venue="polymarket",
        id=m.get("conditionId") or m.get("id", ""),
        title=m.get("question") or m.get("groupItemTitle") or "?",
        yes_token=token_ids[yes_idx],
        no_token=token_ids[no_idx],
    )
