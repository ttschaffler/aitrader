"""Mark-to-market valuation: equity and exposure with multi-currency mix."""

from datetime import date
from decimal import Decimal

import pytest
from src.data.fx import FxRate, FxRates
from src.depot.money import Money
from src.depot.portfolio import Portfolio, Position
from src.depot.valuation import equity, exposure, position_market_value


def _eur_usd(rate: str = "1.10") -> FxRates:
    return FxRates.from_iterable(
        [FxRate("EUR", "USD", Decimal(rate), date(2026, 5, 1))]
    )


def test_position_market_value_stock() -> None:
    pos = Position(
        symbol="AAPL", asset_type="stock", qty=10, avg_price=Money.of("100.00", "USD")
    )
    assert position_market_value(pos, Money.of("150.00", "USD")) == Money.of(
        "1500.00", "USD"
    )


def test_position_market_value_option_uses_100_multiplier() -> None:
    pos = Position(
        symbol="AAPL",
        asset_type="option",
        qty=2,
        avg_price=Money.of("3.00", "USD"),
        expiry=date(2026, 6, 19),
        strike=Money.of("200.00", "USD"),
        right="C",
    )
    # 2 contracts * 100 shares/contract * 5.00 = 1000.00
    assert position_market_value(pos, Money.of("5.00", "USD")) == Money.of(
        "1000.00", "USD"
    )


def test_position_market_value_currency_mismatch_raises() -> None:
    pos = Position(
        symbol="AAPL", asset_type="stock", qty=10, avg_price=Money.of("100.00", "USD")
    )
    with pytest.raises(ValueError, match="quote currency"):
        position_market_value(pos, Money.of("100.00", "EUR"))


def test_equity_cash_only_in_base_currency() -> None:
    p = Portfolio(cash={"EUR": Money.of(50_000, "EUR")})
    assert equity(p, quotes={}, fx=_eur_usd()) == Money.of(50_000, "EUR")


def test_equity_converts_usd_cash_to_eur() -> None:
    p = Portfolio(cash={"EUR": Money.of(40_000, "EUR"), "USD": Money.of(11_000, "USD")})
    # 11_000 USD / 1.10 = 10_000 EUR; total 50_000 EUR
    assert equity(p, quotes={}, fx=_eur_usd()) == Money.of(50_000, "EUR")


def test_equity_includes_position_market_value() -> None:
    p = Portfolio(
        cash={"EUR": Money.of(40_000, "EUR")},
        positions=(
            Position(
                symbol="AAPL",
                asset_type="stock",
                qty=10,
                avg_price=Money.of("100.00", "USD"),
            ),
        ),
    )
    quotes = {"AAPL": Money.of("110.00", "USD")}
    # position value: 10 * 110 USD = 1100 USD = 1000 EUR @ 1.10
    # equity: 40_000 + 1000 = 41_000 EUR
    assert equity(p, quotes=quotes, fx=_eur_usd()) == Money.of(41_000, "EUR")


def test_equity_missing_quote_raises() -> None:
    p = Portfolio(
        cash={"EUR": Money.of(40_000, "EUR")},
        positions=(
            Position(
                symbol="AAPL",
                asset_type="stock",
                qty=10,
                avg_price=Money.of("100.00", "USD"),
            ),
        ),
    )
    with pytest.raises(ValueError, match="missing quote"):
        equity(p, quotes={}, fx=_eur_usd())


def test_exposure_excludes_cash() -> None:
    p = Portfolio(
        cash={"EUR": Money.of(40_000, "EUR")},
        positions=(
            Position(
                symbol="SAP.DE",
                asset_type="stock",
                qty=20,
                avg_price=Money.of("100.00", "EUR"),
            ),
        ),
    )
    quotes = {"SAP.DE": Money.of("120.00", "EUR")}
    assert exposure(p, quotes=quotes, fx=_eur_usd()) == Money.of(2400, "EUR")
