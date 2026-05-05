"""Pure simulation engine — no I/O, no venue knowledge."""

from slippage_labs.engine.book import Book, Level
from slippage_labs.engine.solver import MaxBudgetResult, ReferenceKind, solve_max_budget
from slippage_labs.engine.walker import Fill, FillResult, simulate_buy

__all__ = [
    "Book",
    "Level",
    "Fill",
    "FillResult",
    "MaxBudgetResult",
    "ReferenceKind",
    "simulate_buy",
    "solve_max_budget",
]
