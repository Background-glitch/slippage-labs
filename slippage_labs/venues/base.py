"""Venue abstractions: Side, Market, Event, Venue ABC, and exceptions.

A `Venue` knows how to (a) recognize URLs that belong to it, (b) resolve a URL
to an `Event` (one-or-more `Market`s), and (c) fetch a normalized order Book
for any (Market, Side) pair. The engine doesn't need to know anything else.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

from slippage_labs.engine.book import Book


class Side(str, Enum):
    YES = "yes"
    NO = "no"

    @classmethod
    def parse(cls, raw: str) -> "Side":
        s = raw.strip().lower()
        if s in ("yes", "y"):
            return cls.YES
        if s in ("no", "n"):
            return cls.NO
        raise ValueError(f"Invalid side {raw!r}; expected 'yes' or 'no'")


@dataclass(frozen=True)
class Market:
    """One actionable sub-market. Subclassed per venue to carry fetch metadata."""
    venue: str
    id: str         # canonical venue identifier (token id, market ticker, …)
    title: str      # human-readable question or bucket label


@dataclass(frozen=True)
class Event:
    """A collection of related markets the user can resolve from one URL."""
    venue: str
    id: str                    # event slug / ticker
    title: str
    markets: tuple[Market, ...] = field(default_factory=tuple)
    is_single_market: bool = False   # True if URL pointed at one market, not a wrapper


class Venue(ABC):
    """Adapter for one prediction-market venue."""

    name: str   # set on subclass

    @abstractmethod
    def matches_url(self, url: str) -> bool:
        """Return True if this venue can handle the given URL."""

    @abstractmethod
    def resolve(self, url: str) -> Event:
        """Parse `url` and fetch the Event metadata it points to."""

    @abstractmethod
    def fetch_book(self, market: Market, side: Side) -> Book:
        """Fetch and normalize the order book for one side of one market."""


# ---- exceptions ----

class VenueError(Exception):
    """Base class for venue/network problems."""


class UnsupportedURLError(VenueError):
    """No registered venue claims this URL."""


class MarketNotFoundError(VenueError):
    """The URL parsed but the API returned no matching event/market."""
