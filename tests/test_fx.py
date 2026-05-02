"""FX rate object, pure convert(), and FxRates aggregator."""

from datetime import date
from decimal import Decimal

import pytest
from src.data.fx import FxRate, FxRates, convert
from src.depot.money import Money


def _eur_usd(rate: str = "1.10") -> FxRate:
    return FxRate("EUR", "USD", Decimal(rate), date(2026, 5, 1))


def test_fxrate_rejects_same_currency() -> None:
    with pytest.raises(ValueError):
        FxRate("EUR", "EUR", Decimal("1.0"), date(2026, 5, 1))


def test_fxrate_rejects_non_positive() -> None:
    with pytest.raises(ValueError):
        FxRate("EUR", "USD", Decimal("0"), date(2026, 5, 1))
    with pytest.raises(ValueError):
        FxRate("EUR", "USD", Decimal("-1"), date(2026, 5, 1))


def test_convert_same_currency_is_identity() -> None:
    amount = Money.of(100, "EUR")
    assert convert(amount, "EUR", _eur_usd()) is amount


def test_convert_eur_to_usd_with_rate() -> None:
    # 100 EUR @ 1.10 -> 110 USD
    out = convert(Money.of(100, "EUR"), "USD", _eur_usd("1.10"))
    assert out == Money.of(110, "USD")


def test_convert_usd_to_eur_inverts_rate() -> None:
    # 110 USD / 1.10 -> 100 EUR
    out = convert(Money.of(110, "USD"), "EUR", _eur_usd("1.10"))
    assert out == Money.of(100, "EUR")


def test_convert_uses_bankers_rounding() -> None:
    # 1 EUR -> 1.085 USD with rate 1.085 -> rounds half-even to 1.08
    out = convert(Money.of(1, "EUR"), "USD", _eur_usd("1.085"))
    assert out == Money(108, "USD")


def test_convert_unknown_pair_raises() -> None:
    with pytest.raises(ValueError, match="cannot convert"):
        convert(Money.of(1, "GBP"), "USD", _eur_usd())


def test_fxrates_walks_both_directions() -> None:
    rates = FxRates.from_iterable([_eur_usd("1.10")])
    assert rates.convert(Money.of(100, "EUR"), "USD") == Money.of(110, "USD")
    assert rates.convert(Money.of(110, "USD"), "EUR") == Money.of(100, "EUR")


def test_fxrates_missing_pair_raises() -> None:
    rates = FxRates.from_iterable([_eur_usd("1.10")])
    with pytest.raises(ValueError, match="no rate available"):
        rates.convert(Money.of(1, "GBP"), "EUR")
