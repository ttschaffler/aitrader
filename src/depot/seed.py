"""Seeding logic for the virtual depot.

Kept separate from the CLI in ``scripts/seed_depot.py`` so it can be unit
tested without subprocesses.
"""

from __future__ import annotations

from collections.abc import Iterable

from src.depot.money import Money
from src.depot.portfolio import Portfolio
from src.depot.repository import SQLiteDepotRepository

DEFAULT_CASH_EUR = 50_000
DEFAULT_WATCHLIST: tuple[str, ...] = (
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "AMZN",
    "SAP.DE",
    "SIE.DE",
    "ALV.DE",
    "DTE.DE",
    "BAS.DE",
)


def seed_depot(
    repo: SQLiteDepotRepository,
    *,
    cash_eur: int = DEFAULT_CASH_EUR,
    watchlist: Iterable[str] = DEFAULT_WATCHLIST,
) -> None:
    """Initialize cash and watchlist on a fresh repository.

    Idempotent: calling twice resets to the seed state.
    """
    portfolio = Portfolio(cash={"EUR": Money.of(cash_eur, "EUR")}, positions=())
    repo.save_portfolio(portfolio)
    for symbol in watchlist:
        repo.add_to_watchlist(symbol)
