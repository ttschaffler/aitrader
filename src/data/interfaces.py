"""Role-specific data interfaces and value objects.

Per CLAUDE.md, agent code depends on these Protocols, never on a
concrete adapter. Each Protocol is small (Interface Segregation) so a
caller can declare only what it actually uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol

from src.depot.money import Money

OptionRight = Literal["C", "P"]


@dataclass(frozen=True, slots=True)
class Quote:
    symbol: str
    price: Money
    bid: Money | None
    ask: Money | None
    volume: int | None
    as_of: datetime


@dataclass(frozen=True, slots=True)
class OptionContract:
    underlying: str
    expiry: date
    strike: Money
    right: OptionRight
    last: Money | None
    bid: Money | None
    ask: Money | None
    volume: int | None
    open_interest: int | None


@dataclass(frozen=True, slots=True)
class NewsItem:
    symbol: str
    headline: str
    summary: str
    source: str
    published_at: datetime
    url: str


class QuoteSource(Protocol):
    def get_quote(self, symbol: str) -> Quote: ...


class OptionChainSource(Protocol):
    def get_option_chain(
        self, underlying: str, expiry: date | None = None
    ) -> list[OptionContract]: ...


class NewsSource(Protocol):
    def get_news(self, symbol: str, lookback_hours: int) -> list[NewsItem]: ...
