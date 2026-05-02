"""SMTP-backed ``Notifier``.

Uses stdlib ``smtplib`` + ``email.message`` only. The actual SMTP
delivery is reached via an injectable ``MailSender`` Protocol so tests
can supply an in-memory fake without patching socket-level globals.
"""

from __future__ import annotations

import smtplib
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

from src.notify.formatting import (
    render_daily_summary,
    render_trade_proposal,
    render_weekly_summary,
)
from src.notify.interfaces import (
    DailySummary,
    TradeProposalMessage,
    WeeklySummary,
)


@dataclass(frozen=True, slots=True)
class SmtpConfig:
    host: str
    port: int
    username: str
    password: str
    from_address: str
    to_address: str


class MailSender(Protocol):
    def send(self, message: EmailMessage) -> None: ...


class SmtplibMailSender:  # pragma: no cover - thin I/O shim
    """Default sender that talks to a real SMTP server via STARTTLS."""

    def __init__(self, config: SmtpConfig) -> None:
        self._config = config

    def send(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self._config.host, self._config.port) as smtp:
            smtp.starttls()
            smtp.login(self._config.username, self._config.password)
            smtp.send_message(message)


class SmtpNotifier:
    """Implements the ``Notifier`` Protocol over any ``MailSender``."""

    def __init__(
        self,
        config: SmtpConfig,
        sender_factory: Callable[[SmtpConfig], MailSender] = SmtplibMailSender,
    ) -> None:
        self._config = config
        self._sender = sender_factory(config)

    def _build(self, subject: str, body: str) -> EmailMessage:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self._config.from_address
        msg["To"] = self._config.to_address
        msg.set_content(body)
        return msg

    def send_trade_proposal(self, message: TradeProposalMessage) -> None:
        subject, body = render_trade_proposal(message)
        self._sender.send(self._build(subject, body))

    def send_daily_summary(self, summary: DailySummary) -> None:
        subject, body = render_daily_summary(summary)
        self._sender.send(self._build(subject, body))

    def send_weekly_summary(self, summary: WeeklySummary) -> None:
        subject, body = render_weekly_summary(summary)
        self._sender.send(self._build(subject, body))
