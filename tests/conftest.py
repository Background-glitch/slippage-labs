"""Shared test fixtures and helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from slippage_labs.venues import _http

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict | list:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def fixture_loader():
    """Tests can call `fixture_loader('polymarket_book.json')`."""
    return load_fixture


@pytest.fixture(autouse=True)
def _reset_http_client():
    """Force the venues to recreate the httpx client per test so pytest-httpx can intercept."""
    _http.set_client(None)
    yield
    _http.set_client(None)
