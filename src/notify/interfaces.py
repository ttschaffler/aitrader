"""Notifier interface and the messages it carries.

Per CLAUDE.md the agent depends on this Protocol, not on SMTP. Concrete
notifiers live in sibling modules; the in-memory ``ConsoleNotifier``
fake is reused in tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from src.depot.money import Money
from src.depot.portfolio import Trade


@dataclass(frozen=True, slots=True)
class TradeProposalMessage:
    trade: Trade
    rationale: str
    equity_eur: Money
    cash_eur: Money
    progress_to_goal_pct: float
    proposed_at: datetime


@dataclass(frozen=True, slots=True)
class DailySummary:
    on: date
    equity_eur: Money
    cash_eur: Money
    realized_pnl_eur: Money
    unrealized_pnl_eur: Money
    todays_trade_count: int
    risk_halt_reason: str | None
    progress_to_goal_pct: float


@dataclass(frozen=True, slots=True)
class WeeklySummary:
    week_ending: date
    equity_eur: Money
    week_pnl_eur: Money
    week_pnl_pct: float
    open_position_count: int
    notes: str  # Markdown body produced by report.weekly


class Notifier(Protocol):
    def send_trade_proposal(self, message: TradeProposalMessage) -> None: ...

    def send_daily_summary(self, summary: DailySummary) -> None: ...

    def send_weekly_summary(self, summary: WeeklySummary) -> None: ...
