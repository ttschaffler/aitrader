"""FX conversion: pure functions over daily-cached rates.

The plan mandates that FX conversion never happens inside portfolio
mutation code. Callers fetch rates (or use ``FxRates`` populated from a
provider) and call :func:`convert` explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Protocol

from src.depot.money import Money


@dataclass(frozen=True, slots=True)
class FxRate:
    """One ``base/quote`` rate: ``1 base = rate * quote``."""

    base: str
    quote: str
    rate: Decimal
    as_of: date

    def __post_init__(self) -> None:
        if self.base == self.quote:
            raise ValueError("base and quote currencies must differ")
        if self.rate <= 0:
            raise ValueError("rate must be positive")


def convert(amount: Money, target: str, rate: FxRate) -> Money:
    """Convert ``amount`` to ``target`` currency using ``rate``.

    Pure: identical inputs give identical outputs. Rounds half-to-even
    to the target's minor unit.
    """
    if amount.currency == target:
        return amount

    if amount.currency == rate.base and target == rate.quote:
        factor = rate.rate
    elif amount.currency == rate.quote and target == rate.base:
        factor = Decimal(1) / rate.rate
    else:
        raise ValueError(
            f"cannot convert {amount.currency} to {target} with "
            f"{rate.base}/{rate.quote} rate"
        )

    new_minor = int(
        (Decimal(amount.minor) * factor).quantize(Decimal(1), rounding=ROUND_HALF_EVEN)
    )
    return Money(new_minor, target)


class FxRateProvider(Protocol):
    """Daily-cached FX rate provider.

    Implementations must be safe to call repeatedly within a day without
    repeating network I/O.
    """

    def get_rate(self, base: str, quote: str, on: date) -> FxRate: ...


@dataclass(frozen=True, slots=True)
class FxRates:
    """A snapshot of rates available to a single tick.

    Holds ``(base, quote) -> FxRate``. ``convert`` walks both directions.
    """

    rates: dict[tuple[str, str], FxRate]

    @classmethod
    def from_iterable(cls, rates: list[FxRate]) -> FxRates:
        return cls({(r.base, r.quote): r for r in rates})

    def convert(self, amount: Money, target: str) -> Money:
        if amount.currency == target:
            return amount
        rate = self.rates.get((amount.currency, target)) or self.rates.get(
            (target, amount.currency)
        )
        if rate is None:
            raise ValueError(
                f"no rate available to convert {amount.currency} -> {target}"
            )
        return convert(amount, target, rate)
