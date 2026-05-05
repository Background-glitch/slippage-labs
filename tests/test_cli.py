"""End-to-end CLI tests using Typer's CliRunner + pytest-httpx.

Each test mocks the network calls with the same fixtures used by the venue tests,
so we exercise the whole pipeline (URL parsing -> fetch -> simulate -> render)
without ever touching the live API.
"""

from __future__ import annotations

import json
import re

import pytest
from typer.testing import CliRunner

from slippage_labs.cli import app

runner = CliRunner()


# ---- helpers -----------------------------------------------------------

def _wire_polymarket(httpx_mock, fixture_loader):
    """Mock both Polymarket endpoints used by a sweep."""
    event = fixture_loader("polymarket_event.json")
    book = fixture_loader("polymarket_book.json")

    httpx_mock.add_response(
        url="https://gamma-api.polymarket.com/events?slug=highest-temperature-in-hong-kong-on-may-5-2026",
        json=event,
    )
    # Same book for every token id - tests don't care which side returns what.
    # is_optional so tests that filter to --market 99 don't fail on "unused mock".
    httpx_mock.add_response(
        url=re.compile(r"https://clob\.polymarket\.com/book\?token_id=.*"),
        json=book,
        is_reusable=True,
        is_optional=True,
    )


def _wire_kalshi(httpx_mock, fixture_loader):
    httpx_mock.add_response(
        url="https://api.elections.kalshi.com/trade-api/v2/events/KXHIGHNY-26MAY05",
        json=fixture_loader("kalshi_event.json"),
    )
    httpx_mock.add_response(
        url=re.compile(r"https://api\.elections\.kalshi\.com/trade-api/v2/markets/.*/orderbook"),
        json=fixture_loader("kalshi_book.json"),
        is_reusable=True,
        is_optional=True,
    )


# ---- happy paths -------------------------------------------------------

def test_polymarket_summary_table(httpx_mock, fixture_loader):
    _wire_polymarket(httpx_mock, fixture_loader)
    result = runner.invoke(app, [
        "https://polymarket.com/event/highest-temperature-in-hong-kong-on-may-5-2026",
        "--budget", "100",
    ])
    assert result.exit_code == 0, result.output
    assert "Highest temperature in Hong Kong" in result.output
    assert "polymarket" in result.output
    # Both YES and NO rows for both fixture markets => 4 data rows.
    assert result.output.count("YES") >= 2
    assert result.output.count("NO") >= 2


def test_kalshi_summary_table_via_bare_ticker(httpx_mock, fixture_loader):
    _wire_kalshi(httpx_mock, fixture_loader)
    result = runner.invoke(app, ["KXHIGHNY-26MAY05", "--budget", "200"])
    assert result.exit_code == 0, result.output
    assert "kalshi" in result.output
    assert "76" in result.output and "77" in result.output  # bucket labels


def test_json_output_is_parseable(httpx_mock, fixture_loader):
    _wire_polymarket(httpx_mock, fixture_loader)
    result = runner.invoke(app, [
        "https://polymarket.com/event/highest-temperature-in-hong-kong-on-may-5-2026",
        "--budget", "100",
        "--threshold", "5",
        "--json",
    ])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["venue"] == "polymarket"
    assert payload["budget_usd"] == 100.0
    assert payload["threshold"] == {"pct": 5.0, "reference": "mid"}
    assert len(payload["results"]) == 4   # 2 markets x 2 sides
    r0 = payload["results"][0]
    assert r0["market"]["title"]
    assert r0["side"] in ("yes", "no")
    assert "buy" in r0
    assert "max_budget" in r0
    assert "fills" not in r0["buy"]   # --detailed wasn't passed


def test_json_with_detailed_includes_fills(httpx_mock, fixture_loader):
    _wire_polymarket(httpx_mock, fixture_loader)
    result = runner.invoke(app, [
        "https://polymarket.com/event/highest-temperature-in-hong-kong-on-may-5-2026",
        "--budget", "10",
        "--detailed",
        "--json",
    ])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert all("fills" in r["buy"] for r in payload["results"])


def test_market_filter_limits_to_one(httpx_mock, fixture_loader):
    _wire_polymarket(httpx_mock, fixture_loader)
    result = runner.invoke(app, [
        "https://polymarket.com/event/highest-temperature-in-hong-kong-on-may-5-2026",
        "--budget", "100",
        "--market", "0",
        "--side", "yes",
        "--json",
    ])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert len(payload["results"]) == 1
    assert payload["results"][0]["side"] == "yes"


def test_threshold_adds_max_budget_block(httpx_mock, fixture_loader):
    _wire_kalshi(httpx_mock, fixture_loader)
    result = runner.invoke(app, [
        "KXHIGHNY-26MAY05", "--threshold", "10", "--side", "yes", "--json",
    ])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    for r in payload["results"]:
        assert "max_budget" in r
        mb = r["max_budget"]
        assert "budget" in mb and "feasible" in mb and "threshold_pct" in mb


def test_detailed_text_mode_runs_without_crashing(httpx_mock, fixture_loader):
    _wire_polymarket(httpx_mock, fixture_loader)
    result = runner.invoke(app, [
        "https://polymarket.com/event/highest-temperature-in-hong-kong-on-may-5-2026",
        "--budget", "10", "--detailed", "--side", "yes",
    ])
    assert result.exit_code == 0
    assert "Walking" not in result.output  # we don't say that, but check no crash via section markers
    assert "BUY YES" in result.output


# ---- error paths -------------------------------------------------------

def test_unsupported_url_exits_2():
    result = runner.invoke(app, ["https://example.com/foo"])
    assert result.exit_code == 2
    # Typer routes errors to a separate stream; CliRunner mixes them by default.


def test_market_index_out_of_range(httpx_mock, fixture_loader):
    _wire_polymarket(httpx_mock, fixture_loader)
    result = runner.invoke(app, [
        "https://polymarket.com/event/highest-temperature-in-hong-kong-on-may-5-2026",
        "--market", "99",
    ])
    assert result.exit_code == 2


def test_negative_budget_rejected_by_typer():
    result = runner.invoke(app, [
        "https://polymarket.com/event/foo",
        "--budget", "-10",
    ])
    assert result.exit_code != 0   # typer's range validator catches this


# ---- M4.5 regression: --budget/--threshold reject inf and NaN ----

@pytest.mark.parametrize("flag, value", [
    ("--budget", "inf"),
    ("--budget", "nan"),
    ("--threshold", "inf"),
    ("--threshold", "nan"),
])
def test_non_finite_numeric_flags_rejected(flag, value):
    # Pre-fix `--budget inf` slipped past typer's min= constraint and crashed the walker.
    result = runner.invoke(app, ["KXHIGHNY-26MAY05", flag, value])
    assert result.exit_code != 0
    assert "finite" in (result.output + (result.stderr or "")).lower() or result.exit_code == 2


def test_version_flag_prints_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "slippage-labs" in result.output


@pytest.mark.parametrize("flag, value", [
    ("--reference", "bogus"),
    ("--side", "maybe"),
])
def test_invalid_choice_rejected(flag, value):
    result = runner.invoke(app, ["KXHIGHNY-26MAY05", flag, value])
    assert result.exit_code != 0
