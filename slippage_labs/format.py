"""Renderers for CLI output. Pure presentation — accept simulation results, emit text/JSON."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

from rich.console import Console
from rich.table import Table

from slippage_labs.engine import Book, FillResult, MaxBudgetResult
from slippage_labs.venues import Event, Market, Side


@dataclass(frozen=True)
class MarketSimulation:
    """One (market, side) simulation outcome. View-model for the formatters."""
    market: Market
    side: Side
    book: Book
    fill: FillResult
    max_budget: MaxBudgetResult | None   # None if --threshold wasn't requested


# ---------------------------------------------------------------- pretty table

def render_summary_table(
    sims: list[MarketSimulation],
    event: Event,
    budget: float,
    console: Console,
) -> None:
    """One-row-per-(market, side) compact summary."""
    has_threshold = any(s.max_budget is not None for s in sims)

    title = f"[bold]{event.title}[/bold]   [dim]({event.venue}, ${budget:.0f} order)[/dim]"
    table = Table(title=title, show_lines=False, header_style="bold", expand=False)
    table.add_column("#", justify="right", style="dim", no_wrap=True)
    table.add_column("side", justify="right", no_wrap=True)
    table.add_column("bid", justify="right", no_wrap=True)
    table.add_column("ask", justify="right", no_wrap=True)
    table.add_column("mid", justify="right", no_wrap=True)
    table.add_column("avg fill", justify="right", no_wrap=True)
    table.add_column("slip vs mid", justify="right", no_wrap=True)
    table.add_column("shares", justify="right", no_wrap=True)
    table.add_column("spent", justify="right", no_wrap=True)
    table.add_column("fill", no_wrap=True)
    if has_threshold:
        table.add_column("cap", justify="right", no_wrap=True)
        table.add_column("slip @ cap", justify="right", no_wrap=True)
    table.add_column("market", overflow="ellipsis", max_width=60)

    market_index = {m.id: i for i, m in enumerate(event.markets)}

    for s in sims:
        idx = market_index.get(s.market.id, "?")
        bid = _fmt_price(s.book.best_bid)
        ask = _fmt_price(s.book.best_ask)
        mid = _fmt_price(s.book.mid)
        avg = _fmt_price(s.fill.avg_price)
        slip_mid = _fmt_pct(s.fill.slippage_vs(s.book.mid))
        shares = _fmt_num(s.fill.shares)
        spent = _fmt_money(s.fill.spent)
        fill_tag = _fill_tag(s.fill)

        side_color = "green" if s.side is Side.YES else "red"
        row = [
            str(idx),
            f"[{side_color}]{s.side.value.upper()}[/{side_color}]",
            bid, ask, mid, avg, slip_mid, shares, spent, fill_tag,
        ]
        if has_threshold:
            mb = s.max_budget
            if mb is None:
                row += ["--", "--"]
            elif not mb.feasible:
                row += ["[yellow]infeasible[/yellow]", "--"]
            elif mb.book_bound:
                row += [f"${mb.budget:,.2f}", _fmt_pct(mb.slippage_at_cap_pct) + " [dim]ceil[/dim]"]
            else:
                row += [f"${mb.budget:,.2f}", _fmt_pct(mb.slippage_at_cap_pct)]
        row.append(s.market.title)
        table.add_row(*row)

    console.print(table)


# ---------------------------------------------------------------- detailed walk

def render_detailed(
    sims: list[MarketSimulation],
    event: Event,
    budget: float,
    console: Console,
) -> None:
    """For each (market, side), print summary + the level-by-level walk."""
    console.print(
        f"[bold]{event.title}[/bold]   [dim]({event.venue}, ${budget:.0f} order)[/dim]\n"
    )
    for s in sims:
        side_color = "green" if s.side is Side.YES else "red"
        header = (
            f"[bold]{s.market.title}[/bold]  "
            f"[{side_color}]BUY {s.side.value.upper()}[/{side_color}]  "
            f"[dim]for ${budget:.2f}[/dim]"
        )
        console.print(header)

        if not s.book.asks:
            console.print("  [yellow]Empty ask side - no liquidity to take.[/yellow]\n")
            continue

        bb, ba, mid = s.book.best_bid, s.book.best_ask, s.book.mid
        spread_str = ""
        if bb is not None and mid is not None:
            spread_str = f"   spread ${ba - bb:.4f} ({(ba - bb) / mid * 100:.2f}% of mid)"
        console.print(
            f"  bid={_fmt_price(bb)}  ask={_fmt_price(ba)}  mid={_fmt_price(mid)}{spread_str}"
        )

        walk = Table(show_header=True, header_style="dim", show_lines=False, box=None, padding=(0, 1))
        walk.add_column("lvl", justify="right", style="dim")
        walk.add_column("price", justify="right")
        walk.add_column("size", justify="right")
        walk.add_column("shares taken", justify="right")
        walk.add_column("cost", justify="right")
        walk.add_column("cum shares", justify="right")
        walk.add_column("cum cost", justify="right")
        cum_shares = cum_cost = 0.0
        for i, f in enumerate(s.fill.fills):
            cum_shares += f.shares_taken
            cum_cost += f.cost
            walk.add_row(
                str(i),
                f"{f.level.price:.4f}",
                f"{f.level.size:,.2f}",
                f"{f.shares_taken:,.2f}",
                f"${f.cost:,.2f}",
                f"{cum_shares:,.2f}",
                f"${cum_cost:,.2f}",
            )
        console.print(walk)

        if not s.fill.filled:
            console.print(
                f"  [yellow]!! Order only partially filled - ${s.fill.remaining:.2f} cancelled.[/yellow]"
            )

        slip_mid = s.fill.slippage_vs(mid)
        slip_touch = s.fill.slippage_vs(ba)
        console.print(
            f"  [bold]->[/bold] {s.fill.shares:,.2f} shares for ${s.fill.spent:,.2f}  "
            f"avg [bold]{s.fill.avg_price:.4f}[/bold]  "
            f"slip vs mid {_fmt_pct(slip_mid)}, vs touch {_fmt_pct(slip_touch)}"
        )

        if s.max_budget is not None:
            console.print(_format_max_budget_line(s.max_budget))
        console.print()


def _format_max_budget_line(mb: MaxBudgetResult) -> str:
    if not mb.feasible:
        return (
            f"  [yellow]-> max budget @ {mb.threshold_pct}% slip vs {mb.reference_kind}: "
            f"infeasible[/yellow] [dim](spread alone exceeds threshold)[/dim]"
        )
    note = " [dim](book ceiling - threshold isn't binding)[/dim]" if mb.book_bound else ""
    return (
        f"  [bold]->[/bold] max budget @ {mb.threshold_pct}% slip vs {mb.reference_kind}: "
        f"[bold]${mb.budget:,.2f}[/bold]  "
        f"(at cap, slippage = {mb.slippage_at_cap_pct:+.2f}%){note}"
    )


# ---------------------------------------------------------------- JSON

def render_json(
    sims: list[MarketSimulation],
    event: Event,
    budget: float,
    threshold_pct: float | None,
    reference_kind: str,
    include_fills: bool = False,
) -> str:
    """JSON for piping into jq/scripts. Floats use None for NaN."""
    payload = {
        "venue": event.venue,
        "event": {"id": event.id, "title": event.title},
        "budget_usd": budget,
        "threshold": (
            None if threshold_pct is None
            else {"pct": threshold_pct, "reference": reference_kind}
        ),
        "results": [_sim_to_json(s, include_fills) for s in sims],
    }
    return json.dumps(payload, indent=2, default=_json_default)


def _sim_to_json(s: MarketSimulation, include_fills: bool) -> dict:
    book = {
        "best_bid": _none_if_nan(s.book.best_bid),
        "best_ask": _none_if_nan(s.book.best_ask),
        "mid": _none_if_nan(s.book.mid),
        "ask_depth_levels": len(s.book.asks),
        "ask_total_notional": s.book.total_ask_notional,
    }
    buy = {
        "shares": s.fill.shares,
        "spent": s.fill.spent,
        "remaining": s.fill.remaining,
        "avg_price": _none_if_nan(s.fill.avg_price),
        "filled": s.fill.filled,
        "slippage_vs_touch_pct": s.fill.slippage_vs(s.book.best_ask),
        "slippage_vs_mid_pct": s.fill.slippage_vs(s.book.mid),
    }
    if include_fills:
        buy["fills"] = [
            {"price": f.level.price, "size": f.level.size,
             "shares_taken": f.shares_taken, "cost": f.cost}
            for f in s.fill.fills
        ]

    if s.max_budget is None:
        max_budget_block: dict | None = None
    else:
        mb = s.max_budget
        max_budget_block = {
            "budget": mb.budget,
            "feasible": mb.feasible,
            "book_bound": mb.book_bound,
            "slippage_at_cap_pct": mb.slippage_at_cap_pct,
            "reference_price": _none_if_nan(mb.reference_price),
            "reference_kind": mb.reference_kind,
            "threshold_pct": mb.threshold_pct,
        }
    return {
        "market": {"id": s.market.id, "title": s.market.title},
        "side": s.side.value,
        "book": book,
        "buy": buy,
        "max_budget": max_budget_block,
    }


def _none_if_nan(x: float | None) -> float | None:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return x


def _json_default(obj):
    if isinstance(obj, float) and math.isnan(obj):
        return None
    raise TypeError(f"Not JSON serializable: {type(obj).__name__}")


# ---------------------------------------------------------------- helpers

def _fmt_price(p: float | None) -> str:
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "[dim]n/a[/dim]"
    return f"{p:.4f}"


def _fmt_pct(p: float | None) -> str:
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "[dim]n/a[/dim]"
    color = "green" if p <= 1 else ("yellow" if p <= 10 else "red")
    return f"[{color}]{p:+.2f}%[/{color}]"


def _fmt_num(n: float) -> str:
    return f"{n:,.2f}"


def _fmt_money(n: float) -> str:
    return f"${n:,.2f}"


def _fill_tag(fill: FillResult) -> str:
    if fill.filled:
        return "[green]FULL[/green]"
    if fill.shares == 0:
        return "[red]NONE[/red]"
    return "[yellow]PART[/yellow]"
