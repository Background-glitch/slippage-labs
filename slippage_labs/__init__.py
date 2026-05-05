"""slippage-labs — honest liquidity & slippage analytics for prediction markets."""

__version__ = "0.1.0"

from slippage_labs.engine.book import Book, Level
from slippage_labs.engine.solver import MaxBudgetResult, solve_max_budget
from slippage_labs.engine.walker import Fill, FillResult, simulate_buy
from slippage_labs.urls import venue_for
from slippage_labs.venues import Side, UnsupportedURLError

__all__ = [
    "Book",
    "Level",
    "Fill",
    "FillResult",
    "MaxBudgetResult",
    "simulate_buy",
    "solve_max_budget",
    "Side",
    "UnsupportedURLError",
    "venue_for",
]
