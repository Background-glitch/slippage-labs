# Contributing to slippage-labs

Thanks for the interest. This project values **honest math, small surface area, and easy review** — please keep changes in that spirit.

## Setup

```bash
git clone https://github.com/Background-glitch/slippage-labs
cd slippage-labs
python -m venv .venv && source .venv/bin/activate   # or `.venv\Scripts\activate` on Windows
pip install -e ".[dev]"
pytest
```

Python 3.11+. No system dependencies, no Redis, no database — just the engine, the venue adapters, and the CLI.

## Project layout

```
slippage_labs/
├── engine/        Pure logic (Book, walker, solver). No I/O. Easy to unit-test.
├── venues/        Adapters (Polymarket, Kalshi). Only place that touches HTTP.
├── urls.py        Tiny URL → Venue dispatcher.
├── format.py      Renderers: rich tables / detailed walk / JSON.
└── cli.py         Typer entry point.
tests/             Mirrors the package; uses pytest-httpx + recorded JSON fixtures.
```

The split is deliberate — keep it that way. Engine never imports from venues; venues never import from format/cli.

## Tests

- All tests must pass on every PR. CI runs the matrix (Linux/macOS/Windows × Python 3.11/3.12/3.13).
- Engine tests use hand-crafted books — no fixtures needed.
- Venue tests mock HTTP via `pytest-httpx` and read recorded responses from `tests/fixtures/`. **Do not hit live APIs in tests.**
- CLI tests use `typer.testing.CliRunner` + the same mocks.

If you need to add a fixture, record it once and trim it to the minimum data needed. See the existing files for size targets (~5-15 KB each).

## Adding a new venue

The Venue protocol is small (`venues/base.py`):

1. **Subclass `Venue`** with `name`, `matches_url(url)`, `resolve(url) → Event`, `fetch_book(market, side) → Book`.
2. **If your venue carries extra per-market metadata** (token IDs, tickers, etc.), subclass `Market` and add fields. Keep them frozen.
3. **Wrap `Level` construction** in `try/except (KeyError, TypeError, ValueError)` and re-raise as `VenueError` so the CLI can keep going on a single bad book.
4. **Register it** in `urls.DEFAULT_VENUES`.
5. **Record a fixture** (event endpoint + one orderbook) and add tests covering URL parsing, resolution, and book fetching. Mirror `tests/test_polymarket.py` or `tests/test_kalshi.py`.

If your venue doesn't return asks directly (Kalshi returns bids on each side and we synthesize), do that translation inside `fetch_book` — the engine should always see a normal `Book`.

## Style

- **Don't add features beyond the task.** A bug fix doesn't need a refactor; a one-shot doesn't need a helper.
- **Don't add comments that restate the code.** Save them for *why* something is non-obvious (a workaround, a venue quirk, a hidden invariant).
- **Don't add error handling for things that can't happen.** Trust internal callers; validate at boundaries (user input, API responses).
- Match the existing formatting. There's no enforced linter yet — we'll add one if reviews start arguing about it.

## Commit / PR conventions

- Small, focused PRs are easier to land than sweeping ones.
- Title: imperative, under 70 chars (`fix kalshi 404 message`, not `Fixed an issue with the Kalshi venue when 404s happen`).
- If you change behavior, add or update a regression test in the same PR.
- For non-trivial design changes, open an issue first to align before writing code.

## Releasing (maintainer notes)

1. Bump the version in `pyproject.toml` and `slippage_labs/__init__.py` (`__version__`).
2. Update `CHANGELOG.md` — move "Unreleased" entries under the new version with today's date.
3. Commit, then tag: `git tag v0.X.Y && git push origin v0.X.Y`.
4. The publish workflow uploads to PyPI via Trusted Publishers (no token in repo). Confirm at https://pypi.org/project/slippage-labs/.
