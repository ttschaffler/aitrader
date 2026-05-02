"""EOD snapshot persistence and unrealized P&L."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from src.data.fx import FxRate, FxRates
from src.depot.money import Money
from src.depot.portfolio import Portfolio, Position
from src.depot.repository import SQLiteDepotRepository
from src.report.snapshot import compute_snapshot, take_snapshot


def _eur(amount: int | str) -> Money:
    return Money.of(amount, "EUR")


def _usd(amount: int | str) -> Money:
    return Money.of(amount, "USD")


def _fx() -> FxRates:
    return FxRates.from_iterable(
        [FxRate("EUR", "USD", Decimal("1.10"), date(2026, 5, 1))]
    )


def test_snapshot_cash_only_zero_pnl_zero_exposure() -> None:
    p = Portfolio(cash={"EUR": _eur(50_000)})
    s = compute_snapshot(p, quotes={}, fx=_fx())

    assert s.equity_eur == _eur(50_000)
    assert s.cash_eur == _eur(50_000)
    assert s.exposure_eur == _eur(0)
    assert s.unrealized_pnl_eur == _eur(0)


def test_snapshot_with_winning_position_shows_unrealized_pnl() -> None:
    pos = Position(symbol="AAPL", asset_type="stock", qty=10, avg_price=_usd("100.00"))
    p = Portfolio(cash={"EUR": _eur(40_000)}, positions=(pos,))
    quotes = {"AAPL": _usd("110.00")}

    s = compute_snapshot(p, quotes, _fx())

    # MV = 10 * 110 USD = 1100 USD = 1000 EUR
    # Cost basis = 10 * 100 USD = 1000 USD = 909.09 EUR -> rounds to 909.09 EUR
    # Unrealized = 100 USD = 90.91 EUR (banker's rounding to minor units)
    assert s.exposure_eur == _eur(1_000)
    # 100 USD / 1.10 = 90.9090... -> rounds half-even to 90.91
    assert s.unrealized_pnl_eur == Money(9091, "EUR")
    # equity = cash + position MV
    assert s.equity_eur == _eur(40_000) + _eur(1_000)


def test_take_snapshot_persists_to_repository() -> None:
    repo = SQLiteDepotRepository()
    portfolio = Portfolio(
        cash={"EUR": _eur(40_000)},
        positions=(
            Position(
                symbol="AAPL",
                asset_type="stock",
                qty=10,
                avg_price=_usd("100.00"),
            ),
        ),
    )
    quotes = {"AAPL": _usd("110.00")}
    ts = datetime(2026, 5, 1, 22, 15)

    take_snapshot(repo, ts=ts, portfolio=portfolio, quotes=quotes, fx=_fx())

    snapshots = repo.recent_snapshots()
    assert len(snapshots) == 1
    snap = snapshots[0]
    assert snap["equity_eur"] == _eur(40_000) + _eur(1_000)
    assert snap["exposure_eur"] == _eur(1_000)
    assert snap["ts"] == ts


def test_compute_snapshot_raises_when_position_quote_missing() -> None:
    import pytest

    pos = Position(symbol="AAPL", asset_type="stock", qty=10, avg_price=_usd("100.00"))
    p = Portfolio(cash={"EUR": _eur(40_000)}, positions=(pos,))

    # equity() inside compute_snapshot requires a quote for every held
    # position; missing quotes should fail loudly (the operator can fix
    # the data feed before persisting a misleading snapshot).
    with pytest.raises(ValueError, match="missing quote"):
        compute_snapshot(p, quotes={}, fx=_fx())
