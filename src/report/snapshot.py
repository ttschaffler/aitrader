"""End-of-day snapshot: persist current equity / cash / exposure / PnL.

Pure helpers compute the four numbers; the only I/O is the repository
write. The intended caller is the daily APScheduler job.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from src.data.fx import FxRates
from src.depot.money import Money
from src.depot.portfolio import Portfolio
from src.depot.valuation import equity as compute_equity
from src.depot.valuation import exposure as compute_exposure
from src.depot.valuation import position_market_value


@dataclass(frozen=True, slots=True)
class SnapshotValues:
    equity_eur: Money
    cash_eur: Money
    exposure_eur: Money
    unrealized_pnl_eur: Money


class SnapshotRecorder(Protocol):
    def record_snapshot(
        self,
        *,
        ts: datetime,
        equity_eur: Money,
        cash_eur: Money,
        exposure_eur: Money,
        unrealized_pnl_eur: Money,
    ) -> None: ...


def compute_snapshot(
    portfolio: Portfolio,
    quotes: dict[str, Money],
    fx: FxRates,
) -> SnapshotValues:
    equity_eur = compute_equity(portfolio, quotes, fx)
    exposure_eur = compute_exposure(portfolio, quotes, fx)
    cash_eur = Money.zero("EUR")
    for cash_money in portfolio.cash.values():
        cash_eur = cash_eur + fx.convert(cash_money, "EUR")
    unrealized = _unrealized_pnl(portfolio, quotes, fx)
    return SnapshotValues(
        equity_eur=equity_eur,
        cash_eur=cash_eur,
        exposure_eur=exposure_eur,
        unrealized_pnl_eur=unrealized,
    )


def _unrealized_pnl(
    portfolio: Portfolio, quotes: dict[str, Money], fx: FxRates
) -> Money:
    """Sum of (current MV - cost basis) across all positions, in EUR."""
    pnl = Money.zero("EUR")
    for pos in portfolio.positions:
        last = quotes.get(pos.symbol)
        if last is None:
            continue
        cost_basis_native = pos.avg_price * (
            pos.qty * (100 if pos.asset_type == "option" else 1)
        )
        mv_native = position_market_value(pos, last)
        diff_native = mv_native - cost_basis_native
        pnl = pnl + fx.convert(diff_native, "EUR")
    return pnl


def take_snapshot(
    recorder: SnapshotRecorder,
    *,
    ts: datetime,
    portfolio: Portfolio,
    quotes: dict[str, Money],
    fx: FxRates,
) -> SnapshotValues:
    values = compute_snapshot(portfolio, quotes, fx)
    recorder.record_snapshot(
        ts=ts,
        equity_eur=values.equity_eur,
        cash_eur=values.cash_eur,
        exposure_eur=values.exposure_eur,
        unrealized_pnl_eur=values.unrealized_pnl_eur,
    )
    return values
