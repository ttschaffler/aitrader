"""SQLite depot repository: schema bootstrap, roundtrips, trades, watchlist."""

from datetime import date, datetime
from pathlib import Path

from src.depot.money import Money
from src.depot.portfolio import Portfolio, Position, Trade
from src.depot.repository import SQLiteDepotRepository


def _eur(amount: int | str) -> Money:
    return Money.of(amount, "EUR")


def _usd(amount: int | str) -> Money:
    return Money.of(amount, "USD")


def test_init_creates_schema_for_in_memory_db() -> None:
    with SQLiteDepotRepository() as repo:
        portfolio = repo.load_portfolio()
        assert portfolio.cash == {}
        assert portfolio.positions == ()
        assert repo.watchlist() == []


def test_save_and_load_portfolio_roundtrip() -> None:
    portfolio = Portfolio(
        cash={"EUR": _eur(50_000), "USD": _usd("9000.00")},
        positions=(
            Position(
                symbol="AAPL",
                asset_type="stock",
                qty=10,
                avg_price=_usd("150.00"),
            ),
        ),
    )

    with SQLiteDepotRepository() as repo:
        repo.save_portfolio(portfolio)
        loaded = repo.load_portfolio()

    assert loaded.cash_in("EUR") == _eur(50_000)
    assert loaded.cash_in("USD") == _usd("9000.00")
    assert len(loaded.positions) == 1
    pos = loaded.positions[0]
    assert pos.symbol == "AAPL"
    assert pos.qty == 10
    assert pos.avg_price == _usd("150.00")


def test_save_and_load_option_position_roundtrip() -> None:
    expiry = date(2026, 6, 19)
    portfolio = Portfolio(
        cash={"USD": _usd(10_000)},
        positions=(
            Position(
                symbol="AAPL",
                asset_type="option",
                qty=2,
                avg_price=_usd("3.50"),
                expiry=expiry,
                strike=_usd("200.00"),
                right="C",
            ),
        ),
    )

    with SQLiteDepotRepository() as repo:
        repo.save_portfolio(portfolio)
        loaded = repo.load_portfolio()

    pos = loaded.positions[0]
    assert pos.asset_type == "option"
    assert pos.expiry == expiry
    assert pos.strike == _usd("200.00")
    assert pos.right == "C"


def test_save_overwrites_previous_state() -> None:
    first = Portfolio(cash={"EUR": _eur(50_000)})
    second = Portfolio(cash={"EUR": _eur(40_000)})

    with SQLiteDepotRepository() as repo:
        repo.save_portfolio(first)
        repo.save_portfolio(second)
        loaded = repo.load_portfolio()

    assert loaded.cash_in("EUR") == _eur(40_000)


def test_record_trade_persists_row() -> None:
    trade = Trade(
        symbol="AAPL",
        asset_type="stock",
        side="BUY",
        qty=10,
        price=_usd("150.00"),
        fees=_usd("1.00"),
    )

    with SQLiteDepotRepository() as repo:
        assert repo.trade_count() == 0
        repo.record_trade(
            trade,
            ts=datetime(2026, 5, 1, 14, 30, 0),
            rationale="momentum entry",
            fx_rate=1.0850,
        )
        assert repo.trade_count() == 1


def test_watchlist_dedup_and_ordering() -> None:
    with SQLiteDepotRepository() as repo:
        repo.add_to_watchlist("MSFT")
        repo.add_to_watchlist("AAPL", notes="apple")
        repo.add_to_watchlist("AAPL", notes="updated")  # upsert
        assert repo.watchlist() == ["AAPL", "MSFT"]


def test_persistence_across_connections(tmp_path: Path) -> None:
    db = tmp_path / "depot.sqlite"

    with SQLiteDepotRepository(db) as repo:
        repo.save_portfolio(Portfolio(cash={"EUR": _eur(50_000)}))
        repo.add_to_watchlist("AAPL")

    with SQLiteDepotRepository(db) as repo:
        loaded = repo.load_portfolio()
        assert loaded.cash_in("EUR") == _eur(50_000)
        assert repo.watchlist() == ["AAPL"]
