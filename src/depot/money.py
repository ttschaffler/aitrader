"""Money value object: integer minor units + ISO 4217 currency code.

Internal accounting uses minor units (e.g. cents) as ``int`` to avoid
float drift. Money is immutable; arithmetic returns new instances and
mixed-currency operations raise.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

_CURRENCY_LEN = 3
_MINOR_SCALE = 2


@dataclass(frozen=True, slots=True)
class Money:
    minor: int
    currency: str

    def __post_init__(self) -> None:
        if isinstance(self.minor, bool) or not isinstance(self.minor, int):
            raise TypeError(f"minor must be int, got {type(self.minor).__name__}")
        if len(self.currency) != _CURRENCY_LEN or not self.currency.isalpha():
            raise ValueError(
                f"currency must be 3 alphabetic letters, got {self.currency!r}"
            )
        if self.currency != self.currency.upper():
            raise ValueError(f"currency must be uppercase, got {self.currency!r}")

    @classmethod
    def zero(cls, currency: str) -> Money:
        return cls(0, currency)

    @classmethod
    def of(cls, major: Decimal | str | int, currency: str) -> Money:
        """Build from major units (e.g. ``Money.of("12.34", "EUR")``)."""
        minor = int((Decimal(major) * (10**_MINOR_SCALE)).to_integral_value())
        return cls(minor, currency)

    @property
    def major(self) -> Decimal:
        return Decimal(self.minor) / Decimal(10**_MINOR_SCALE)

    def _check_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise ValueError(f"currency mismatch: {self.currency} vs {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._check_currency(other)
        return Money(self.minor + other.minor, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check_currency(other)
        return Money(self.minor - other.minor, self.currency)

    def __mul__(self, factor: int) -> Money:
        if isinstance(factor, bool) or not isinstance(factor, int):
            raise TypeError(
                f"can only multiply Money by int, got {type(factor).__name__}"
            )
        return Money(self.minor * factor, self.currency)

    __rmul__ = __mul__

    def __neg__(self) -> Money:
        return Money(-self.minor, self.currency)

    def is_negative(self) -> bool:
        return self.minor < 0

    def is_zero(self) -> bool:
        return self.minor == 0

    def __str__(self) -> str:
        sign = "-" if self.minor < 0 else ""
        whole, frac = divmod(abs(self.minor), 10**_MINOR_SCALE)
        return f"{sign}{whole}.{frac:0{_MINOR_SCALE}d} {self.currency}"
