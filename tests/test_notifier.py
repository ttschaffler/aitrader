"""Notifier formatting and SMTP delivery (with an in-memory MailSender)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from email.message import EmailMessage

import pytest
from src.depot.money import Money
from src.depot.portfolio import Trade
from src.notify.console_notifier import ConsoleNotifier
from src.notify.interfaces import DailySummary, TradeProposalMessage, WeeklySummary
from src.notify.smtp_notifier import SmtpConfig, SmtpNotifier


def _stock_trade() -> Trade:
    return Trade(
        symbol="AAPL",
        asset_type="stock",
        side="BUY",
        qty=10,
        price=Money.of("150.00", "USD"),
        fees=Money.of("1.00", "USD"),
    )


def _option_trade() -> Trade:
    return Trade(
        symbol="AAPL",
        asset_type="option",
        side="BUY",
        qty=1,
        price=Money.of("3.50", "USD"),
        fees=Money.of("0.65", "USD"),
        expiry=date(2026, 6, 19),
        strike=Money.of("200.00", "USD"),
        right="C",
    )


def _proposal(trade: Trade) -> TradeProposalMessage:
    return TradeProposalMessage(
        trade=trade,
        rationale="momentum entry on 50dma cross",
        equity_eur=Money.of(50_000, "EUR"),
        cash_eur=Money.of(48_500, "EUR"),
        progress_to_goal_pct=50.0,
        proposed_at=datetime(2026, 5, 1, 14, 30, tzinfo=UTC),
    )


def test_console_notifier_captures_trade_proposal_subject_and_body() -> None:
    notifier = ConsoleNotifier()

    notifier.send_trade_proposal(_proposal(_stock_trade()))

    assert len(notifier.sent) == 1
    sent = notifier.sent[0]
    assert sent.kind == "trade"
    assert sent.subject == "[aitrader] BUY 10 AAPL STOCK"
    assert "Rationale: momentum entry" in sent.body
    assert "Equity:   50000.00 EUR" in sent.body
    assert "Goal:     50.00% of target" in sent.body


def test_trade_proposal_for_option_includes_expiry_strike_right() -> None:
    notifier = ConsoleNotifier()
    notifier.send_trade_proposal(_proposal(_option_trade()))

    sent = notifier.sent[0]
    assert "2026-06-19" in sent.subject
    assert "C @ strike 200.00 USD" in sent.subject


def test_console_notifier_renders_daily_summary_with_halt_reason() -> None:
    notifier = ConsoleNotifier()
    summary = DailySummary(
        on=date(2026, 5, 1),
        equity_eur=Money.of(48_000, "EUR"),
        cash_eur=Money.of(20_000, "EUR"),
        realized_pnl_eur=Money.of(-500, "EUR"),
        unrealized_pnl_eur=Money.of(-1_500, "EUR"),
        todays_trade_count=3,
        risk_halt_reason="daily loss cutoff",
        progress_to_goal_pct=48.0,
    )
    notifier.send_daily_summary(summary)

    sent = notifier.sent[0]
    assert sent.kind == "daily"
    assert sent.subject == "[aitrader] Daily summary 2026-05-01"
    assert "Realized:    -500.00 EUR" in sent.body
    assert "Risk halt:   daily loss cutoff" in sent.body


def test_console_notifier_renders_weekly_summary_markdown_body() -> None:
    notifier = ConsoleNotifier()
    summary = WeeklySummary(
        week_ending=date(2026, 5, 3),
        equity_eur=Money.of(52_000, "EUR"),
        week_pnl_eur=Money.of(2_000, "EUR"),
        week_pnl_pct=4.0,
        open_position_count=4,
        notes="### Top movers\n- AAPL +5%",
    )
    notifier.send_weekly_summary(summary)

    sent = notifier.sent[0]
    assert sent.kind == "weekly"
    assert sent.subject == "[aitrader] Weekly review 2026-05-03"
    assert "# Weekly review 2026-05-03" in sent.body
    assert "Week P&L: 2000.00 EUR (+4.00%)" in sent.body
    assert "Top movers" in sent.body


# ---------------------------------------------------------------- SMTP path
class _CapturingMailSender:
    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        self.messages.append(message)


def test_smtp_notifier_builds_and_sends_email() -> None:
    sender = _CapturingMailSender()
    config = SmtpConfig(
        host="smtp.example.com",
        port=587,
        username="bot@example.com",
        password="x",
        from_address="bot@example.com",
        to_address="me@example.com",
    )
    notifier = SmtpNotifier(config, sender_factory=lambda _c: sender)

    notifier.send_trade_proposal(_proposal(_stock_trade()))

    assert len(sender.messages) == 1
    msg = sender.messages[0]
    assert msg["From"] == "bot@example.com"
    assert msg["To"] == "me@example.com"
    assert msg["Subject"].startswith("[aitrader] BUY 10 AAPL")
    assert "Rationale:" in msg.get_content()


def test_smtp_notifier_sends_all_three_message_types() -> None:
    sender = _CapturingMailSender()
    config = SmtpConfig(
        host="h",
        port=587,
        username="u",
        password="p",
        from_address="f@e.com",
        to_address="t@e.com",
    )
    notifier = SmtpNotifier(config, sender_factory=lambda _c: sender)

    notifier.send_trade_proposal(_proposal(_stock_trade()))
    notifier.send_daily_summary(
        DailySummary(
            on=date(2026, 5, 1),
            equity_eur=Money.of(50_000, "EUR"),
            cash_eur=Money.of(50_000, "EUR"),
            realized_pnl_eur=Money.zero("EUR"),
            unrealized_pnl_eur=Money.zero("EUR"),
            todays_trade_count=0,
            risk_halt_reason=None,
            progress_to_goal_pct=50.0,
        )
    )
    notifier.send_weekly_summary(
        WeeklySummary(
            week_ending=date(2026, 5, 3),
            equity_eur=Money.of(50_000, "EUR"),
            week_pnl_eur=Money.zero("EUR"),
            week_pnl_pct=0.0,
            open_position_count=0,
            notes="",
        )
    )

    assert [m["Subject"] for m in sender.messages] == [
        "[aitrader] BUY 10 AAPL STOCK",
        "[aitrader] Daily summary 2026-05-01",
        "[aitrader] Weekly review 2026-05-03",
    ]


def test_console_notifier_echo_writes_to_stream() -> None:
    import io

    buf = io.StringIO()
    notifier = ConsoleNotifier(echo=True, stream=buf)
    notifier.send_trade_proposal(_proposal(_stock_trade()))

    output = buf.getvalue()
    assert "=== [aitrader] BUY 10 AAPL STOCK ===" in output
    assert "Rationale:" in output


@pytest.mark.parametrize(
    "kind,sender_call",
    [
        ("trade", lambda n: n.send_trade_proposal(_proposal(_stock_trade()))),
    ],
)
def test_console_notifier_default_does_not_print(
    kind: str, sender_call: object
) -> None:
    import io

    buf = io.StringIO()
    notifier = ConsoleNotifier(echo=False, stream=buf)
    sender_call(notifier)  # type: ignore[operator]

    assert buf.getvalue() == ""
    assert len(notifier.sent) == 1
    assert notifier.sent[0].kind == kind
