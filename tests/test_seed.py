"""Seeding the virtual depot."""

from src.depot.money import Money
from src.depot.repository import SQLiteDepotRepository
from src.depot.seed import DEFAULT_WATCHLIST, seed_depot


def test_seed_creates_50k_eur_cash_and_default_watchlist() -> None:
    with SQLiteDepotRepository() as repo:
        seed_depot(repo)
        portfolio = repo.load_portfolio()

        assert portfolio.cash_in("EUR") == Money.of(50_000, "EUR")
        assert portfolio.positions == ()
        assert set(repo.watchlist()) == set(DEFAULT_WATCHLIST)


def test_seed_with_custom_cash_amount() -> None:
    with SQLiteDepotRepository() as repo:
        seed_depot(repo, cash_eur=25_000)
        assert repo.load_portfolio().cash_in("EUR") == Money.of(25_000, "EUR")


def test_seed_is_idempotent() -> None:
    with SQLiteDepotRepository() as repo:
        seed_depot(repo)
        seed_depot(repo)
        portfolio = repo.load_portfolio()

        assert portfolio.cash_in("EUR") == Money.of(50_000, "EUR")
        # watchlist contains exactly the default set, not duplicated
        assert sorted(repo.watchlist()) == sorted(DEFAULT_WATCHLIST)


def test_seed_with_custom_watchlist() -> None:
    with SQLiteDepotRepository() as repo:
        seed_depot(repo, watchlist=("FOO", "BAR"))
        assert sorted(repo.watchlist()) == ["BAR", "FOO"]
