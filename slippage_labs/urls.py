"""URL → Venue dispatch."""

from __future__ import annotations

from slippage_labs.venues import Kalshi, Polymarket, UnsupportedURLError, Venue

# Order matters: more specific matchers first if there's ever overlap.
DEFAULT_VENUES: tuple[Venue, ...] = (Polymarket(), Kalshi())


def venue_for(url: str, venues: tuple[Venue, ...] = DEFAULT_VENUES) -> Venue:
    """Return the first registered venue that claims this URL.

    Raises `UnsupportedURLError` if nothing matches.
    """
    for v in venues:
        if v.matches_url(url):
            return v
    raise UnsupportedURLError(
        f"No venue adapter recognizes {url!r}. "
        f"Supported: {', '.join(v.name for v in venues)}."
    )
