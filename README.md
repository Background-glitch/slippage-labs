# slippage-labs

> Honest liquidity & slippage analytics for prediction markets.

Paste a Polymarket or Kalshi market URL and an order size. `slippage-labs` walks the live order book and tells you what you'd actually pay — average fill price, slippage vs mid, and (optionally) the largest order the market can absorb without blowing past a slippage threshold you set.

No alpha, no signals, no opinions on outcomes. Just transparent liquidity math.

## Install

```bash
pip install slippage-labs           # once published to PyPI
# or, from source:
git clone https://github.com/Background-glitch/slippage-labs
cd slippage-labs
pip install -e ".[dev]"
```

Requires Python 3.11+. Works on macOS, Linux, and Windows.

## Quick start

```bash
# What would $500 cost across every sub-market in this Polymarket event?
slippage-labs https://polymarket.com/event/highest-temperature-in-hong-kong-on-may-5-2026 --budget 500

# Same thing on Kalshi — paste the URL or just the event ticker.
slippage-labs KXHIGHNY-26MAY05 --budget 500
```

Output is a per-(market, side) table: best bid/ask, mid, your average fill, slippage vs mid, shares acquired, and whether the order fully filled.

## What it answers

### "What's a fair size for this market?"

Add `--threshold X` to also compute the largest budget that stays within X% slippage vs mid:

```bash
slippage-labs <url> --budget 500 --threshold 2
```

Each row gains a "cap" column showing the recommended max size *and the realized slippage at that cap* — so you see "$132 cap, +1.97% slip" rather than just a number to trust blindly.

If even the smallest possible buy already exceeds your threshold (because the spread alone is too wide), the row reads `infeasible`. That's a feature: a 1% threshold on a market with a 3% spread is silently nonsense, and we'd rather say so.

### "Walk me through the fill, level by level"

```bash
slippage-labs <url> --budget 500 --detailed
```

Prints the full order-book walk for each (market, side) — every level taken, cumulative shares, cumulative cost. Useful when the summary number surprises you and you want to see *why*.

### "Pipe this into another tool"

```bash
slippage-labs <url> --budget 500 --threshold 2 --json | jq '.results[] | select(.max_budget.feasible == false)'
```

`--json` emits a stable schema: top-level `venue`, `event`, `budget_usd`, `threshold`, then a `results` array of `{market, side, book, buy, max_budget}`.

## All options

```
slippage-labs URL [OPTIONS]

  URL                       Polymarket or Kalshi URL, or a bare Kalshi event ticker.
  --budget, -b AMOUNT       Order size in USD. Default: 500.
  --threshold, -t PCT       Also report max budget under this slippage %.
  --reference, -r [mid|touch]  Slippage reference for --threshold. Default: mid.
  --side, -s [yes|no|both]  Default: both.
  --market, -m INDEX        Limit to one sub-market (run plain to list).
  --detailed, -d            Print the level-by-level walk.
  --json                    Emit JSON instead of pretty output.
  --version
  --help
```

## Slippage methodology

- **Walk** — asks consumed cheapest-first until budget is exhausted. Any leftover budget is treated as **cancelled** (IOC semantics), not rested.
- **Slippage vs mid** is the default reference because it's harder to game with stale 1-share quotes. Use `--reference touch` if you'd rather measure against best ask (matches what the venue UI shows).
- **Max-size solver** binary-searches the budget axis. Three regimes: *infeasible* (spread alone exceeds threshold), *book-bound* (whole ask side fits), or *threshold-bound* (somewhere inside the book).

## What's modeled — and what isn't

This tool answers a narrow question (**"what would I pay for this much exposure right now?"**) honestly. It does not answer adjacent questions, and the difference matters:

- **Buy only.** Slippage is computed for opening a position. Selling out is not modeled; exit slippage can be very different (and often worse on illiquid markets).
- **Marketable IOC.** The walk assumes you're crossing the spread for an immediate fill. Any leftover budget after the book is exhausted is reported as cancelled, not rested as a limit bid. If you'd post a passive bid instead, the math doesn't apply.
- **Pre-fee.** Slippage numbers ignore venue fees, withdrawal/deposit costs, and bridge spreads. A 0% slippage entry can still be a losing trade after fees.
- **Snapshot, not stream.** Each sub-market's book is fetched sequentially. A sweep over an event with 11 sub-markets takes ~2-3 seconds, during which earlier books may have moved. The output is a snapshot at slightly different times for each row, not an atomic capture.
- **Liquidity-safe ≠ price-safe.** The recommended cap tells you the market can absorb that much without crushing your average fill. It says nothing about whether the *price itself* is fair. A 1.5% slippage entry at a stupid price is still a stupid trade.
- **Mid is mechanical.** When the spread is wide, `(bid + ask) / 2` is a fictional reference and slippage-vs-mid percentages can look insane (e.g., +10,000%). Treat large slippage numbers on wide-spread markets as a signal that the book itself isn't real, not as a precise measurement.
- **Minimum order sizes ignored.** Polymarket and Kalshi both have minimums (e.g., 5 shares). The simulator will happily compute fills below them; real orders would be rejected.

## Supported venues

| Venue | URL shape | Notes |
|---|---|---|
| Polymarket | `polymarket.com/event/<slug>` | Uses Gamma API for events, CLOB API for books. |
| Kalshi | `kalshi.com/...` containing an event ticker, or the ticker itself (`KXHIGHNY-26MAY05`) | Public API, no auth. Asks are synthesized from opposite-side bids. |

Single-market URLs (`polymarket.com/market/<slug>`) are recognized and emit a clear "use the event URL instead" message in v0.1; first-class single-market support is on the v0.2 list.

## AI Use Statement
This project was developed with AI assistance (Claude, Codex, etc) for drafting, refactoring, and test scaffolding. All code paths, venue assumptions, edge cases, and tests were manually reviewed and revised by the maintainer.

## Development

```bash
pip install -e ".[dev]"
pytest                       # ~85 tests, no live API calls
```

The engine (walker + solver) is pure Python with no dependencies — see `slippage_labs/engine/`. Venue adapters (`slippage_labs/venues/`) implement a small protocol; adding a third venue is one file plus a fixture.

## License

MIT — see [LICENSE](LICENSE).
