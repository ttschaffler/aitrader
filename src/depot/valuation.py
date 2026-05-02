"""Mark-to-market valuation: pure functions over a Portfolio + market snapshot.

Equity is the sum of all cash buckets plus the market value of every open
position, all converted into the depot's base currency (EUR).

Kept in ``src.depot`` (read-only over the domain) but explicitly free of
network I/O — the caller passes already-fetched quotes and FX rates.
"""

from __future__ import annotations

from src.data.fx import FxRates
from src.depot.money import Money
from src.depot.portfolio import Portfolio, Position

# Each US-style equity option contract represents 100 underlying shares.
_OPTION_CONTRACT_MULTIPLIER = 100


def position_market_value(position: Position, last_price: Money) -> Money:
    if last_price.currency != position.avg_price.currency:
        raise ValueError(
            f"quote currency {last_price.currency} mismatches position "
            f"currency {position.avg_price.currency} for {position.symbol}"
        )
    multiplier = _OPTION_CONTRACT_MULTIPLIER if position.asset_type == "option" else 1
    return last_price * (position.qty * multiplier)


def equity(
    portfolio: Portfolio,
    quotes: dict[str, Money],
    fx: FxRates,
    base_currency: str = "EUR",
) -> Money:
    """Total portfolio equity in ``base_currency``."""
    total = Money.zero(base_currency)

    for cash_money in portfolio.cash.values():
        total = total + fx.convert(cash_money, base_currency)

    for pos in portfolio.positions:
        last_price = quotes.get(pos.symbol)
        if last_price is None:
            raise ValueError(f"missing quote for held position {pos.symbol}")
        mv = position_market_value(pos, last_price)
        total = total + fx.convert(mv, base_currency)

    return total


def exposure(
    portfolio: Portfolio,
    quotes: dict[str, Money],
    fx: FxRates,
    base_currency: str = "EUR",
) -> Money:
    """Sum of market values of all open positions in ``base_currency``."""
    total = Money.zero(base_currency)
    for pos in portfolio.positions:
        last_price = quotes.get(pos.symbol)
        if last_price is None:
            raise ValueError(f"missing quote for held position {pos.symbol}")
        total = total + fx.convert(
            position_market_value(pos, last_price), base_currency
        )
    return total
