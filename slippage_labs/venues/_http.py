"""Shared HTTP client for venue adapters.

Module-level singleton so we get connection pooling across calls within one
process, with a sensible UA and timeout. Tests can swap it out via
`set_client(...)` if they ever need to bypass pytest-httpx.
"""

from __future__ import annotations

import httpx

from slippage_labs import __version__

USER_AGENT = f"slippage-labs/{__version__} (+https://github.com/yourusername/slippage-labs)"
DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=10.0)

_client: httpx.Client | None = None


def get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )
    return _client


def set_client(client: httpx.Client | None) -> None:
    """Override the shared client (mostly for tests). Pass None to reset."""
    global _client
    _client = client
