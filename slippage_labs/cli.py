"""slippage-labs CLI — paste a market URL, get honest slippage numbers."""

from __future__ import annotations

import math
from enum import Enum
from typing import Annotated

import httpx
import typer
from rich.console import Console

from slippage_labs import __version__
from slippage_labs.engine import simulate_buy, solve_max_budget
from slippage_labs.format import (
    MarketSimulation,
    render_detailed,
    render_json,
    render_summary_table,
)
from slippage_labs.urls import venue_for
from slippage_labs.venues import (
    MarketNotFoundError,
    Side,
    UnsupportedURLError,
    VenueError,
)

app = typer.Typer(
    add_completion=False,
    rich_markup_mode="rich",
    help=(
        "Honest liquidity & slippage analytics for prediction markets.\n\n"
        "Paste a Polymarket or Kalshi URL (or a Kalshi event ticker like "
        "[bold]KXHIGHNY-26MAY05[/bold]) and an order size. The tool walks the "
        "live order book and reports what you'd actually pay."
    ),
)


class SideChoice(str, Enum):
    yes = "yes"
    no = "no"
    both = "both"


class ReferenceChoice(str, Enum):
    mid = "mid"
    touch = "touch"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"slippage-labs {__version__}")
        raise typer.Exit()


def _require_finite(value: float | None) -> float | None:
    """Typer callback: reject inf/NaN. Typer's range constraint doesn't catch these."""
    if value is None:
        return value
    if math.isnan(value) or math.isinf(value):
        raise typer.BadParameter(f"must be a finite number; got {value!r}")
    return value


@app.command()
def main(
    url: Annotated[str, typer.Argument(
        help="Polymarket or Kalshi URL, or a bare Kalshi event ticker."
    )],
    budget: Annotated[float, typer.Option(
        "--budget", "-b",
        help="Order size in USD.",
        min=0.01,
        callback=_require_finite,
    )] = 500.0,
    threshold: Annotated[float | None, typer.Option(
        "--threshold", "-t",
        help="Also report the largest budget that stays under this slippage % "
             "(measured against --reference). Default: not computed.",
        min=0.0,
        callback=_require_finite,
    )] = None,
    reference: Annotated[ReferenceChoice, typer.Option(
        "--reference", "-r",
        help="Slippage reference for --threshold.",
        case_sensitive=False,
    )] = ReferenceChoice.mid,
    side: Annotated[SideChoice, typer.Option(
        "--side", "-s",
        help="Which side(s) to simulate.",
        case_sensitive=False,
    )] = SideChoice.both,
    market: Annotated[int | None, typer.Option(
        "--market", "-m",
        help="Limit to one sub-market by index (run without to see the list).",
        min=0,
    )] = None,
    detailed: Annotated[bool, typer.Option(
        "--detailed", "-d",
        help="Print the level-by-level walk for every market (verbose).",
    )] = False,
    as_json: Annotated[bool, typer.Option(
        "--json",
        help="Emit JSON instead of pretty output (for piping into jq/scripts).",
    )] = False,
    version: Annotated[bool, typer.Option(
        "--version", callback=_version_callback, is_eager=True,
    )] = False,
) -> None:
    """Walk the live order book for a market URL and report slippage."""
    # When stdout isn't a TTY (piping, redirection, tests) Rich would auto-shrink
    # to ~80 cols and wrap the table column-by-column — pin a wide width instead.
    import sys
    console = Console(
        soft_wrap=False,
        width=None if sys.stdout.isatty() else 200,
    )
    err_console = Console(stderr=True)

    try:
        venue = venue_for(url)
    except UnsupportedURLError as e:
        err_console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from None

    sides = _expand_sides(side)

    try:
        with err_console.status(f"[dim]Resolving {venue.name} URL…[/dim]"):
            event = venue.resolve(url)
    except MarketNotFoundError as e:
        err_console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=2) from None
    except (httpx.HTTPError, VenueError) as e:
        err_console.print(f"[red]network error:[/red] {e}")
        raise typer.Exit(code=1) from None

    targets = _select_markets(event, market)
    if not targets:
        err_console.print(
            f"[red]error:[/red] --market {market} out of range "
            f"(event has {len(event.markets)} sub-markets, indices 0..{len(event.markets)-1})"
        )
        raise typer.Exit(code=2)

    sims: list[MarketSimulation] = []
    total = len(targets) * len(sides)
    with err_console.status("") as status:
        for n, (m, s) in enumerate(((m, s) for m in targets for s in sides), start=1):
            status.update(f"[dim]Fetching book {n}/{total}: {m.title[:60]} ({s.value})[/dim]")
            try:
                book = venue.fetch_book(m, s)
            except (httpx.HTTPError, VenueError) as e:
                err_console.print(f"[yellow]skip[/yellow] {m.title} ({s.value}): {e}")
                continue
            fill = simulate_buy(book, budget)
            mb = None
            if threshold is not None:
                try:
                    mb = solve_max_budget(book, threshold, reference=reference.value)
                except ValueError:
                    mb = None  # e.g. --reference mid on a one-sided book
            sims.append(MarketSimulation(market=m, side=s, book=book, fill=fill, max_budget=mb))

    if not sims:
        err_console.print("[red]error:[/red] no order books could be fetched.")
        raise typer.Exit(code=1)

    if as_json:
        console.print_json(render_json(
            sims, event, budget,
            threshold_pct=threshold,
            reference_kind=reference.value,
            include_fills=detailed,
        ))
    elif detailed:
        render_detailed(sims, event, budget, console)
    else:
        render_summary_table(sims, event, budget, console)


def _expand_sides(s: SideChoice) -> list[Side]:
    if s is SideChoice.both:
        return [Side.YES, Side.NO]
    return [Side.YES if s is SideChoice.yes else Side.NO]


def _select_markets(event, index: int | None):
    if index is None:
        return list(event.markets)
    if index < 0 or index >= len(event.markets):
        return []
    return [event.markets[index]]


if __name__ == "__main__":
    app()
