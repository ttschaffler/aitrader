"""Portfolio buy/sell math and immutability."""

from datetime import date

import pytest
from src.depot.money import Money
from src.depot.portfolio import Portfolio, Position, Trade


def _eur(amount: int | str) -> Money:
    return Money.of(amount, "EUR")


def _usd(amount: int | str) -> Money:
    return Money.of(amount, "USD")


def _empty(starting_eur: int = 50_000) -> Portfolio:
    return Portfolio(cash={"EUR": _eur(starting_eur)})


def _stock_buy(symbol: str, qty: int, price: Money, fees: Money) -> Trade:
    return Trade(
        symbol=symbol,
        asset_type="stock",
        side="BUY",
        qty=qty,
        price=price,
        fees=fees,
    )


def _stock_sell(symbol: str, qty: int, price: Money, fees: Money) -> Trade:
    return Trade(
        symbol=symbol,
        asset_type="stock",
        side="SELL",
        qty=qty,
        price=price,
        fees=fees,
    )


def test_buy_creates_new_position_and_debits_cash() -> None:
    p = _empty().apply(_stock_buy("AAPL", 10, _eur("150.00"), _eur("1.00")))

    assert len(p.positions) == 1
    pos = p.positions[0]
    assert pos.symbol == "AAPL"
    assert pos.qty == 10
    assert pos.avg_price == _eur("150.00")
    # 50000 - (10 * 150 + 1) = 48499.00
    assert p.cash_in("EUR") == _eur("48499.00")


def test_buying_more_lots_weights_avg_price() -> None:
    p = (
        _empty()
        .apply(_stock_buy("AAPL", 10, _eur("100.00"), _eur(0)))
        .apply(_stock_buy("AAPL", 10, _eur("200.00"), _eur(0)))
    )

    pos = p.positions[0]
    assert pos.qty == 20
    # weighted avg: (10*100 + 10*200) / 20 = 150
    assert pos.avg_price == _eur("150.00")
    # 50000 - 1000 - 2000 = 47000
    assert p.cash_in("EUR") == _eur("47000.00")


def test_partial_sell_reduces_qty_and_credits_cash() -> None:
    p = _empty().apply(_stock_buy("AAPL", 10, _eur("100.00"), _eur(0)))
    p = p.apply(_stock_sell("AAPL", 4, _eur("120.00"), _eur("0.50")))

    pos = p.positions[0]
    assert pos.qty == 6
    assert pos.avg_price == _eur("100.00")  # avg unchanged on sell
    # cash: (50000 - 1000) + (4*120 - 0.50) = 49000 + 479.50 = 49479.50
    assert p.cash_in("EUR") == _eur("49479.50")


def test_full_sell_removes_position() -> None:
    p = _empty().apply(_stock_buy("AAPL", 10, _eur("100.00"), _eur(0)))
    p = p.apply(_stock_sell("AAPL", 10, _eur("110.00"), _eur(0)))

    assert p.positions == ()
    # 50000 - 1000 + 1100 = 50100
    assert p.cash_in("EUR") == _eur("50100.00")


def test_sell_more_than_held_raises() -> None:
    p = _empty().apply(_stock_buy("AAPL", 10, _eur("100.00"), _eur(0)))
    with pytest.raises(ValueError, match="exceeds held qty"):
        p.apply(_stock_sell("AAPL", 11, _eur("110.00"), _eur(0)))


def test_sell_unknown_position_raises() -> None:
    with pytest.raises(ValueError, match="no position to sell"):
        _empty().apply(_stock_sell("AAPL", 1, _eur("100.00"), _eur(0)))


def test_buy_with_separate_currency_uses_separate_cash_bucket() -> None:
    start = Portfolio(cash={"EUR": _eur(50_000), "USD": _usd(10_000)})
    p = start.apply(_stock_buy("AAPL", 10, _usd("100.00"), _usd(0)))

    assert p.cash_in("EUR") == _eur(50_000)  # untouched
    assert p.cash_in("USD") == _usd("9000.00")
    assert p.positions[0].avg_price.currency == "USD"


def test_apply_returns_new_portfolio_original_unchanged() -> None:
    original = _empty()
    after = original.apply(_stock_buy("AAPL", 10, _eur("100.00"), _eur(0)))

    assert original.positions == ()
    assert original.cash_in("EUR") == _eur(50_000)
    assert after is not original


def test_option_trade_requires_expiry_strike_right() -> None:
    with pytest.raises(ValueError, match="option trades require"):
        Trade(
            symbol="AAPL",
            asset_type="option",
            side="BUY",
            qty=1,
            price=_usd("5.00"),
            fees=_usd(0),
        )


def test_option_position_keyed_by_expiry_strike_right() -> None:
    expiry = date(2026, 6, 19)
    strike = _usd("200.00")
    pos = Position(
        symbol="AAPL",
        asset_type="option",
        qty=2,
        avg_price=_usd("3.50"),
        expiry=expiry,
        strike=strike,
        right="C",
    )
    portfolio = Portfolio(cash={"USD": _usd(10_000)}, positions=(pos,))

    same_key_trade = Trade(
        symbol="AAPL",
        asset_type="option",
        side="BUY",
        qty=1,
        price=_usd("4.00"),
        fees=_usd(0),
        expiry=expiry,
        strike=strike,
        right="C",
    )
    diff_strike_trade = Trade(
        symbol="AAPL",
        asset_type="option",
        side="BUY",
        qty=1,
        price=_usd("4.00"),
        fees=_usd(0),
        expiry=expiry,
        strike=_usd("210.00"),
        right="C",
    )

    after_same = portfolio.apply(same_key_trade)
    after_diff = portfolio.apply(diff_strike_trade)

    assert len(after_same.positions) == 1
    assert after_same.positions[0].qty == 3
    assert len(after_diff.positions) == 2


def test_negative_price_or_fees_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        Trade(
            symbol="AAPL",
            asset_type="stock",
            side="BUY",
            qty=1,
            price=Money(-1, "EUR"),
            fees=_eur(0),
        )


def test_zero_qty_rejected() -> None:
    with pytest.raises(ValueError, match="trade qty must be positive"):
        Trade(
            symbol="AAPL",
            asset_type="stock",
            side="BUY",
            qty=0,
            price=_eur(1),
            fees=_eur(0),
        )
