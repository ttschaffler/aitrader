"""Risk guardrails: pure rule functions + a composing checker.

Each rule is a small pure function that takes already-computed inputs
and returns ``RiskResult``. There is no network, no DB write, no clock
side effect — callers (typically ``trader.py``) supply ``now``, fx
rates, equity, etc.

Rules covered (one function per rule, one test per rule):
- session hours (per-market open/close)
- 30 min close cutoff
- daily loss cutoff (-3%)
- weekly loss cutoff (-8%)
- per-trade options premium <= 2% equity
- total open options premium <= 10% equity
- single-name exposure ≤ 10% equity
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from src.data.fx import FxRates
from src.depot.money import Money
from src.depot.portfolio import Portfolio, Trade

OPTION_CONTRACT_MULTIPLIER = 100


# --------------------------------------------------------------------- result
@dataclass(frozen=True, slots=True)
class Approved:
    pass


@dataclass(frozen=True, slots=True)
class Rejected:
    reason: str


RiskResult = Approved | Rejected


@dataclass(frozen=True, slots=True)
class RiskConfig:
    max_single_name_pct: float = 0.10
    max_total_premium_pct: float = 0.10
    max_per_trade_premium_pct: float = 0.02
    daily_loss_cutoff_pct: float = -0.03
    weekly_loss_cutoff_pct: float = -0.08
    cutoff_minutes_before_close: int = 30


# -------------------------------------------------------------------- markets
class Market(StrEnum):
    US = "US"
    XETRA = "XETRA"


@dataclass(frozen=True, slots=True)
class SessionHours:
    open_h: int
    open_m: int
    close_h: int
    close_m: int


# Local-time hours in Europe/Berlin. Approximate during US DST shifts;
# acceptable for a paper-trading guardrail and easily refined later.
_SESSIONS: dict[Market, SessionHours] = {
    Market.US: SessionHours(15, 30, 22, 0),
    Market.XETRA: SessionHours(9, 0, 17, 30),
}

_BERLIN = ZoneInfo("Europe/Berlin")


def market_for_symbol(symbol: str) -> Market:
    return Market.XETRA if symbol.upper().endswith(".DE") else Market.US


def _close_dt(now_local: datetime, hours: SessionHours) -> datetime:
    return now_local.replace(
        hour=hours.close_h, minute=hours.close_m, second=0, microsecond=0
    )


def _open_dt(now_local: datetime, hours: SessionHours) -> datetime:
    return now_local.replace(
        hour=hours.open_h, minute=hours.open_m, second=0, microsecond=0
    )


# --------------------------------------------------------------------- rules
def check_session_hours(
    trade: Trade, now: datetime, tz: ZoneInfo = _BERLIN
) -> RiskResult:
    market = market_for_symbol(trade.symbol)
    hours = _SESSIONS[market]
    local = now.astimezone(tz)
    if local.weekday() >= 5:
        return Rejected(f"{market.value} session closed: weekend")
    if not _open_dt(local, hours) <= local <= _close_dt(local, hours):
        return Rejected(f"outside {market.value} session hours")
    return Approved()


def check_close_cutoff(
    trade: Trade,
    now: datetime,
    config: RiskConfig,
    tz: ZoneInfo = _BERLIN,
) -> RiskResult:
    market = market_for_symbol(trade.symbol)
    hours = _SESSIONS[market]
    local = now.astimezone(tz)
    cutoff = _close_dt(local, hours) - timedelta(
        minutes=config.cutoff_minutes_before_close
    )
    if local >= cutoff:
        return Rejected(
            f"within {config.cutoff_minutes_before_close} min of {market.value} close"
        )
    return Approved()


def check_daily_loss_cutoff(daily_pnl_pct: float, config: RiskConfig) -> RiskResult:
    if daily_pnl_pct <= config.daily_loss_cutoff_pct:
        return Rejected(
            f"daily P&L {daily_pnl_pct * 100:.2f}% breaches cutoff "
            f"{config.daily_loss_cutoff_pct * 100:.2f}%"
        )
    return Approved()


def check_weekly_loss_cutoff(weekly_pnl_pct: float, config: RiskConfig) -> RiskResult:
    if weekly_pnl_pct <= config.weekly_loss_cutoff_pct:
        return Rejected(
            f"weekly P&L {weekly_pnl_pct * 100:.2f}% breaches cutoff "
            f"{config.weekly_loss_cutoff_pct * 100:.2f}%"
        )
    return Approved()


def option_premium(trade: Trade) -> Money:
    """USD/EUR-style listed option premium: price * qty * 100."""
    if trade.asset_type != "option":
        return Money.zero(trade.price.currency)
    return trade.price * (trade.qty * OPTION_CONTRACT_MULTIPLIER)


def check_per_trade_premium_cap(
    trade: Trade,
    equity_eur: Money,
    fx: FxRates,
    config: RiskConfig,
) -> RiskResult:
    if trade.asset_type != "option" or trade.side != "BUY":
        return Approved()
    premium_eur = fx.convert(option_premium(trade), "EUR")
    cap_minor = int(equity_eur.minor * config.max_per_trade_premium_pct)
    if premium_eur.minor > cap_minor:
        return Rejected(
            f"option premium {premium_eur} exceeds "
            f"{config.max_per_trade_premium_pct * 100:.1f}% cap "
            f"{Money(cap_minor, 'EUR')}"
        )
    return Approved()


def check_total_open_premium_cap(
    trade: Trade,
    portfolio: Portfolio,
    quotes: dict[str, Money],
    equity_eur: Money,
    fx: FxRates,
    config: RiskConfig,
) -> RiskResult:
    """Sum of all open long-option premium (in EUR), incl. the proposed trade."""
    if equity_eur.minor <= 0:
        return Rejected("non-positive equity")

    total = Money.zero("EUR")
    for pos in portfolio.positions:
        if pos.asset_type != "option":
            continue
        last = quotes.get(pos.symbol) or pos.avg_price
        position_value = last * (pos.qty * OPTION_CONTRACT_MULTIPLIER)
        total = total + fx.convert(position_value, "EUR")

    if trade.asset_type == "option" and trade.side == "BUY":
        total = total + fx.convert(option_premium(trade), "EUR")

    cap_minor = int(equity_eur.minor * config.max_total_premium_pct)
    if total.minor > cap_minor:
        return Rejected(
            f"total open option premium {total} exceeds "
            f"{config.max_total_premium_pct * 100:.1f}% cap "
            f"{Money(cap_minor, 'EUR')}"
        )
    return Approved()


def check_single_name_cap(
    trade: Trade,
    portfolio: Portfolio,
    quotes: dict[str, Money],
    equity_eur: Money,
    fx: FxRates,
    config: RiskConfig,
) -> RiskResult:
    if trade.side != "BUY":
        return Approved()
    if equity_eur.minor <= 0:
        return Rejected("non-positive equity")

    multiplier = OPTION_CONTRACT_MULTIPLIER if trade.asset_type == "option" else 1
    new_notional_native = trade.price * (trade.qty * multiplier)

    existing = Money.zero(trade.price.currency)
    for pos in portfolio.positions:
        if pos.symbol != trade.symbol:
            continue
        last = quotes.get(pos.symbol) or pos.avg_price
        pos_mult = OPTION_CONTRACT_MULTIPLIER if pos.asset_type == "option" else 1
        contribution = last * (pos.qty * pos_mult)
        if contribution.currency == existing.currency:
            existing = existing + contribution
        else:
            existing = existing + fx.convert(contribution, existing.currency)

    total_eur = fx.convert(existing + new_notional_native, "EUR")
    cap_minor = int(equity_eur.minor * config.max_single_name_pct)
    if total_eur.minor > cap_minor:
        return Rejected(
            f"single-name exposure on {trade.symbol} {total_eur} exceeds "
            f"{config.max_single_name_pct * 100:.1f}% cap "
            f"{Money(cap_minor, 'EUR')}"
        )
    return Approved()


# ------------------------------------------------------------------ composer
@dataclass(frozen=True, slots=True)
class RiskInputs:
    trade: Trade
    portfolio: Portfolio
    quotes: dict[str, Money]
    fx: FxRates
    equity_eur: Money
    daily_pnl_pct: float
    weekly_pnl_pct: float
    now: datetime


class RiskChecker:
    """Walks every rule in a deterministic order and returns the first
    rejection or ``Approved``. Pure: holds only configuration."""

    def __init__(self, config: RiskConfig, tz: ZoneInfo = _BERLIN) -> None:
        self.config = config
        self.tz = tz

    def check(self, inputs: RiskInputs) -> RiskResult:
        results = (
            check_daily_loss_cutoff(inputs.daily_pnl_pct, self.config),
            check_weekly_loss_cutoff(inputs.weekly_pnl_pct, self.config),
            check_session_hours(inputs.trade, inputs.now, self.tz),
            check_close_cutoff(inputs.trade, inputs.now, self.config, self.tz),
            check_per_trade_premium_cap(
                inputs.trade, inputs.equity_eur, inputs.fx, self.config
            ),
            check_total_open_premium_cap(
                inputs.trade,
                inputs.portfolio,
                inputs.quotes,
                inputs.equity_eur,
                inputs.fx,
                self.config,
            ),
            check_single_name_cap(
                inputs.trade,
                inputs.portfolio,
                inputs.quotes,
                inputs.equity_eur,
                inputs.fx,
                self.config,
            ),
        )
        for r in results:
            if isinstance(r, Rejected):
                return r
        return Approved()
