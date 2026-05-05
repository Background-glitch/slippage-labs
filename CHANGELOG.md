# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-05-04

First public release. CLI for honest slippage analytics on prediction markets.

### Added

- **Engine** (`slippage_labs/engine/`): pure Python, zero dependencies.
  - `Book` / `Level` with canonical sort and validation (rejects `price ≤ 0`,
    NaN/inf prices, negative sizes — fails fast on corrupt API data).
  - `simulate_buy(book, budget)` walks asks cheapest-first; IOC semantics
    (leftover budget reported as cancelled, not rested).
  - `solve_max_budget(book, threshold_pct, reference)` binary-searches for the
    largest budget that stays under a slippage threshold (vs `mid` or `touch`).
    Distinguishes infeasible / book-bound / threshold-bound regimes.
- **Venue adapters** (`slippage_labs/venues/`):
  - **Polymarket** via Gamma + CLOB APIs. Event URLs (`/event/<slug>`).
    `/market/<slug>` URLs emit a clear "use the event URL" message.
  - **Kalshi** via the public trade API. Accepts kalshi.com URLs containing an
    event ticker, or a bare ticker pasted directly. Synthesizes asks from
    opposite-side bids (Kalshi quirk). 404s suggest event-vs-market ticker
    confusion when the input has 3+ dash-separated segments.
- **CLI** (`slippage-labs <url> ...`): three output modes (compact summary
  table, level-by-level walk, JSON), `--threshold` for max-size solving,
  `--reference [mid|touch]`, `--side`, `--market`, `--detailed`, `--json`.
- **Tests**: 85 tests, ~20s, no live API calls (pytest-httpx with recorded
  fixtures). Cross-platform CI on push (Linux/macOS/Windows × Python 3.11/3.12/3.13).
- **Docs**: README with install, usage examples, slippage methodology, and
  explicit "what's modeled / what isn't" section.

[Unreleased]: https://github.com/yourusername/slippage-labs/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/yourusername/slippage-labs/releases/tag/v0.1.0
