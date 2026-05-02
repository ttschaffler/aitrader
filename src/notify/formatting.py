"""Plain-text email body rendering.

Pure functions: take a message dataclass, return ``(subject, body)``.
Kept separate from delivery so SMTP and console notifiers share the
exact same wording, and tests can pin the format.
"""

from __future__ import annotations

from src.notify.interfaces import DailySummary, TradeProposalMessage, WeeklySummary


def render_trade_proposal(msg: TradeProposalMessage) -> tuple[str, str]:
    t = msg.trade
    side = t.side
    qty = t.qty
    asset = t.asset_type.upper()
    detail = f"{t.symbol} {asset}" + (
        f" {t.expiry.isoformat()} {t.right} @ strike {t.strike}"
        if t.asset_type == "option" and t.strike and t.expiry
        else ""
    )
    subject = f"[aitrader] {side} {qty} {detail}"

    body_lines = [
        f"Proposed: {side} {qty} x {detail}",
        f"Price:    {t.price}",
        f"Fees:     {t.fees}",
        "",
        f"Rationale: {msg.rationale}",
        "",
        f"Equity:   {msg.equity_eur}",
        f"Cash:     {msg.cash_eur}",
        f"Goal:     {msg.progress_to_goal_pct:.2f}% of target",
        "",
        f"Proposed at: {msg.proposed_at.isoformat()}",
    ]
    return subject, "\n".join(body_lines)


def render_daily_summary(summary: DailySummary) -> tuple[str, str]:
    subject = f"[aitrader] Daily summary {summary.on.isoformat()}"
    body_lines = [
        f"Date:        {summary.on.isoformat()}",
        f"Equity:      {summary.equity_eur}",
        f"Cash:        {summary.cash_eur}",
        f"Realized:    {summary.realized_pnl_eur}",
        f"Unrealized:  {summary.unrealized_pnl_eur}",
        f"Trades:      {summary.todays_trade_count}",
        f"Goal:        {summary.progress_to_goal_pct:.2f}% of target",
    ]
    if summary.risk_halt_reason:
        body_lines.append(f"Risk halt:   {summary.risk_halt_reason}")
    return subject, "\n".join(body_lines)


def render_weekly_summary(summary: WeeklySummary) -> tuple[str, str]:
    subject = f"[aitrader] Weekly review {summary.week_ending.isoformat()}"
    body = (
        f"# Weekly review {summary.week_ending.isoformat()}\n\n"
        f"- Equity: {summary.equity_eur}\n"
        f"- Week P&L: {summary.week_pnl_eur} ({summary.week_pnl_pct:+.2f}%)\n"
        f"- Open positions: {summary.open_position_count}\n\n"
        f"{summary.notes}\n"
    )
    return subject, body
