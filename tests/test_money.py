"""Money value object: arithmetic, immutability, and currency safety."""

from decimal import Decimal

import pytest
from src.depot.money import Money


def test_zero_has_zero_minor_and_currency() -> None:
    m = Money.zero("EUR")
    assert m.minor == 0
    assert m.currency == "EUR"
    assert m.is_zero()


def test_of_converts_major_to_minor() -> None:
    assert Money.of("12.34", "EUR").minor == 1234
    assert Money.of(Decimal("100"), "USD").minor == 10_000
    assert Money.of(50_000, "EUR").minor == 5_000_000


def test_major_property_returns_decimal_in_major_units() -> None:
    assert Money(1234, "EUR").major == Decimal("12.34")
    assert Money(-50, "USD").major == Decimal("-0.50")


def test_addition_same_currency() -> None:
    assert Money(100, "EUR") + Money(50, "EUR") == Money(150, "EUR")


def test_addition_different_currency_raises() -> None:
    with pytest.raises(ValueError, match="currency mismatch"):
        _ = Money(100, "EUR") + Money(50, "USD")


def test_subtraction_can_go_negative() -> None:
    result = Money(100, "EUR") - Money(150, "EUR")
    assert result.minor == -50
    assert result.is_negative()


def test_multiplication_by_int_scales_minor() -> None:
    assert Money(250, "EUR") * 4 == Money(1000, "EUR")
    assert 4 * Money(250, "EUR") == Money(1000, "EUR")


def test_multiplication_by_float_raises() -> None:
    with pytest.raises(TypeError):
        _ = Money(100, "EUR") * 1.5  # type: ignore[operator]


def test_multiplication_by_bool_raises() -> None:
    with pytest.raises(TypeError):
        _ = Money(100, "EUR") * True  # type: ignore[operator]


def test_negation_flips_sign() -> None:
    assert -Money(123, "EUR") == Money(-123, "EUR")


def test_immutability_frozen_dataclass() -> None:
    m = Money(100, "EUR")
    with pytest.raises(AttributeError):
        m.minor = 200  # type: ignore[misc]


def test_currency_must_be_three_uppercase_letters() -> None:
    with pytest.raises(ValueError):
        Money(0, "EU")
    with pytest.raises(ValueError):
        Money(0, "eur")
    with pytest.raises(ValueError):
        Money(0, "EU1")


def test_minor_must_be_int_not_float_or_bool() -> None:
    with pytest.raises(TypeError):
        Money(1.5, "EUR")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Money(True, "EUR")  # type: ignore[arg-type]


def test_str_renders_with_two_decimals_and_sign() -> None:
    assert str(Money(1234, "EUR")) == "12.34 EUR"
    assert str(Money(-50, "USD")) == "-0.50 USD"
    assert str(Money(0, "EUR")) == "0.00 EUR"
