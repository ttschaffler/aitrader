"""Pure domain model for the virtual depot.

Holds cash and positions and applies trades as immutable transformations.
No I/O lives here — that is the job of ``src.depot.repository``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from typing import Literal

from src.depot.money import Money

AssetType = Literal["stock", "option"]
Side = Literal["BUY", "SELL"]
Right = Literal["C", "P"]


PositionKey = tuple[str, AssetType, date | None, Money | None, Right | None]


@dataclass(frozen=True, slots=True)
class Position:
    symbol: str
    asset_type: AssetType
    qty: int
    avg_price: Money
    expiry: date | None = None
    strike: Money | None = None
    right: Right | None = None

    def __post_init__(self) -> None:
        if self.qty <= 0:
            raise ValueError("position qty must be positive")
        if self.asset_type == "option" and (
            self.expiry is None or self.strike is None or self.right is None
        ):
            raise ValueError("option positions require expiry, strike, right")

    def key(self) -> PositionKey:
        return (self.symbol, self.asset_type, self.expiry, self.strike, self.right)


@dataclass(frozen=True, slots=True)
class Trade:
    symbol: str
    asset_type: AssetType
    side: Side
    qty: int
    price: Money
    fees: Money
    expiry: date | None = None
    strike: Money | None = None
    right: Right | None = None

    def __post_init__(self) -> None:
        if self.qty <= 0:
            raise ValueError("trade qty must be positive")
        if self.price.is_negative() or self.fees.is_negative():
            raise ValueError("trade price and fees must be non-negative")
        if self.price.currency != self.fees.currency:
            raise ValueError("price and fees must share currency")
        if self.asset_type == "option" and (
            self.expiry is None or self.strike is None or self.right is None
        ):
            raise ValueError("option trades require expiry, strike, right")

    def position_key(self) -> PositionKey:
        return (self.symbol, self.asset_type, self.expiry, self.strike, self.right)


@dataclass(frozen=True, slots=True)
class Portfolio:
    """Cash balances by currency and currently held positions.

    All mutators (``apply``) return a new ``Portfolio``; the instance is
    treated as immutable.
    """

    cash: dict[str, Money] = field(default_factory=dict)
    positions: tuple[Position, ...] = ()

    def cash_in(self, currency: str) -> Money:
        return self.cash.get(currency, Money.zero(currency))

    def find(self, key: PositionKey) -> Position | None:
        for p in self.positions:
            if p.key() == key:
                return p
        return None

    def apply(self, trade: Trade) -> Portfolio:
        return self._buy(trade) if trade.side == "BUY" else self._sell(trade)

    def _buy(self, t: Trade) -> Portfolio:
        currency = t.price.currency
        cost = t.price * t.qty + t.fees
        new_cash = dict(self.cash)
        new_cash[currency] = self.cash_in(currency) - cost

        existing = self.find(t.position_key())
        if existing is None:
            new_positions = (
                *self.positions,
                Position(
                    symbol=t.symbol,
                    asset_type=t.asset_type,
                    qty=t.qty,
                    avg_price=t.price,
                    expiry=t.expiry,
                    strike=t.strike,
                    right=t.right,
                ),
            )
        else:
            total_qty = existing.qty + t.qty
            total_cost_minor = (
                existing.avg_price.minor * existing.qty + t.price.minor * t.qty
            )
            new_avg = Money(total_cost_minor // total_qty, currency)
            updated = replace(existing, qty=total_qty, avg_price=new_avg)
            new_positions = tuple(
                updated if p.key() == existing.key() else p for p in self.positions
            )

        return Portfolio(cash=new_cash, positions=new_positions)

    def _sell(self, t: Trade) -> Portfolio:
        existing = self.find(t.position_key())
        if existing is None:
            raise ValueError(f"no position to sell: {t.symbol}")
        if t.qty > existing.qty:
            raise ValueError(
                f"sell qty {t.qty} exceeds held qty {existing.qty} for {t.symbol}"
            )
        if t.price.currency != existing.avg_price.currency:
            raise ValueError(
                f"sell currency {t.price.currency} mismatches position "
                f"currency {existing.avg_price.currency}"
            )

        currency = t.price.currency
        proceeds = t.price * t.qty - t.fees
        new_cash = dict(self.cash)
        new_cash[currency] = self.cash_in(currency) + proceeds

        if t.qty == existing.qty:
            new_positions = tuple(
                p for p in self.positions if p.key() != existing.key()
            )
        else:
            updated = replace(existing, qty=existing.qty - t.qty)
            new_positions = tuple(
                updated if p.key() == existing.key() else p for p in self.positions
            )

        return Portfolio(cash=new_cash, positions=new_positions)
