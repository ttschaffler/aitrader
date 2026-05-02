"""In-memory ``Notifier`` used as a fake in tests and for dev runs.

Captures every send so tests can assert on subject/body, and prints the
body when ``echo=True`` for ad-hoc local runs.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import TextIO

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


@dataclass
class SentMessage:
    kind: str  # "trade" | "daily" | "weekly"
    subject: str
    body: str


@dataclass
class ConsoleNotifier:
    echo: bool = False
    stream: TextIO = field(default_factory=lambda: sys.stdout)
    sent: list[SentMessage] = field(default_factory=list)

    def _capture(self, kind: str, subject: str, body: str) -> None:
        self.sent.append(SentMessage(kind, subject, body))
        if self.echo:
            self.stream.write(f"=== {subject} ===\n{body}\n")

    def send_trade_proposal(self, message: TradeProposalMessage) -> None:
        self._capture("trade", *render_trade_proposal(message))

    def send_daily_summary(self, summary: DailySummary) -> None:
        self._capture("daily", *render_daily_summary(summary))

    def send_weekly_summary(self, summary: WeeklySummary) -> None:
        self._capture("weekly", *render_weekly_summary(summary))
