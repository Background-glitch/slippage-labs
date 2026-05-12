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
        markets = tuple(filter(None, (_try_parse_market(m) for m in ev.get("markets", []))))
        if not markets:
            raise MarketNotFoundError(
                f"Polymarket event {slug!r} has no binary (Yes/No) markets we can price."
            )
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
            bids = [Level(float(b["price"]), float(b["size"])) for b in (raw.get("bids") or [])]
            asks = [Level(float(a["price"]), float(a["size"])) for a in (raw.get("asks") or [])]
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
    """Translate one entry from Gamma's `markets` array into a PolymarketMarket.

    Raises ValueError for non-binary outcomes or missing token ids — callers
    should decide whether to skip the sub-market or fail the whole event.
    """
    outcomes_raw = json.loads(m["outcomes"])       # e.g. ["Yes", "No"]
    outcomes = [str(o).strip().lower() for o in outcomes_raw]
    token_ids = json.loads(m["clobTokenIds"])      # aligned with outcomes
    if "yes" not in outcomes or "no" not in outcomes:
        raise ValueError(f"non-binary outcomes {outcomes_raw!r}")
    if len(token_ids) != len(outcomes):
        raise ValueError("clobTokenIds length doesn't match outcomes")
    yes_idx = outcomes.index("yes")
    no_idx = outcomes.index("no")
    if not token_ids[yes_idx] or not token_ids[no_idx]:
        raise ValueError("empty clobTokenId for Yes or No outcome")
    return PolymarketMarket(
        venue="polymarket",
        id=m.get("conditionId") or m.get("id", ""),
        title=m.get("question") or m.get("groupItemTitle") or "?",
        yes_token=token_ids[yes_idx],
        no_token=token_ids[no_idx],
    )


def _try_parse_market(m: dict) -> PolymarketMarket | None:
    """Best-effort parse — return None for malformed/non-binary sub-markets."""
    try:
        return _parse_market(m)
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return None
