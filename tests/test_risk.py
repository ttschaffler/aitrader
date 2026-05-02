"""Risk rules: one test per rule, plus the composer."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.agent.risk import (
    Approved,
    Rejected,
    RiskChecker,
    RiskConfig,
    RiskInputs,
    check_close_cutoff,
    check_daily_loss_cutoff,
    check_per_trade_premium_cap,
    check_session_hours,
    check_single_name_cap,
    check_total_open_premium_cap,
    check_weekly_loss_cutoff,
)
from src.data.fx import FxRate, FxRates
from src.depot.money import Money
from src.depot.portfolio import Portfolio, Position, Trade

_BERLIN = ZoneInfo("Europe/Berlin")


def _eur(amount: int | str) -> Money:
    return Money.of(amount, "EUR")


def _usd(amount: int | str) -> Money:
    return Money.of(amount, "USD")


def _fx(rate: str = "1.10") -> FxRates:
    return FxRates.from_iterable(
        [FxRate("EUR", "USD", Decimal(rate), date(2026, 5, 1))]
    )


def _stock_buy(symbol: str, qty: int, price: Money, fees: Money | None = None) -> Trade:
    return Trade(
        symbol=symbol,
        asset_type="stock",
        side="BUY",
        qty=qty,
        price=price,
        fees=fees or Money.zero(price.currency),
    )


def _option_buy(qty: int, price: Money) -> Trade:
    return Trade(
        symbol="AAPL",
        asset_type="option",
        side="BUY",
        qty=qty,
        price=price,
        fees=Money.zero(price.currency),
        expiry=date(2026, 6, 19),
        strike=_usd("200.00"),
        right="C",
    )


def _berlin(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=_BERLIN)


# --------------------------------------------------------- 1. session hours
def test_session_hours_us_open_inside_session() -> None:
    trade = _stock_buy("AAPL", 1, _usd(100))
    # Friday at 16:00 Berlin is inside US 15:30-22:00
    assert check_session_hours(trade, _berlin(2026, 5, 1, 16, 0)) == Approved()


def test_session_hours_us_too_early_rejected() -> None:
    trade = _stock_buy("AAPL", 1, _usd(100))
    result = check_session_hours(trade, _berlin(2026, 5, 1, 14, 0))
    assert isinstance(result, Rejected)
    assert "outside US session" in result.reason


def test_session_hours_xetra_inside() -> None:
    trade = _stock_buy("SAP.DE", 1, _eur(100))
    assert check_session_hours(trade, _berlin(2026, 5, 1, 10, 0)) == Approved()


def test_session_hours_weekend_rejected() -> None:
    trade = _stock_buy("AAPL", 1, _usd(100))
    # 2026-05-02 is a Saturday
    result = check_session_hours(trade, _berlin(2026, 5, 2, 16, 0))
    assert isinstance(result, Rejected)
    assert "weekend" in result.reason


# --------------------------------------------------------- 2. close cutoff
def test_close_cutoff_blocks_last_30_min_us() -> None:
    cfg = RiskConfig()
    trade = _stock_buy("AAPL", 1, _usd(100))
    result = check_close_cutoff(trade, _berlin(2026, 5, 1, 21, 35), cfg)
    assert isinstance(result, Rejected)
    assert "close" in result.reason


def test_close_cutoff_allows_earlier() -> None:
    cfg = RiskConfig()
    trade = _stock_buy("AAPL", 1, _usd(100))
    assert check_close_cutoff(trade, _berlin(2026, 5, 1, 21, 25), cfg) == Approved()


# --------------------------------------------------------- 3. daily loss
def test_daily_loss_cutoff_at_threshold_rejects() -> None:
    cfg = RiskConfig()
    result = check_daily_loss_cutoff(-0.03, cfg)
    assert isinstance(result, Rejected)


def test_daily_loss_cutoff_above_threshold_allowed() -> None:
    cfg = RiskConfig()
    assert check_daily_loss_cutoff(-0.029, cfg) == Approved()


# --------------------------------------------------------- 4. weekly loss
def test_weekly_loss_cutoff_below_threshold_rejected() -> None:
    cfg = RiskConfig()
    result = check_weekly_loss_cutoff(-0.10, cfg)
    assert isinstance(result, Rejected)


def test_weekly_loss_cutoff_above_threshold_allowed() -> None:
    cfg = RiskConfig()
    assert check_weekly_loss_cutoff(-0.05, cfg) == Approved()


# ----------------------------------------------------- 5. per-trade premium
def test_per_trade_premium_cap_within_limit() -> None:
    cfg = RiskConfig()
    # 1 contract * 100 * $5 = $500 -> ~454 EUR @ 1.10 — within 2% of 50k = 1000 EUR
    trade = _option_buy(1, _usd("5.00"))
    assert check_per_trade_premium_cap(trade, _eur(50_000), _fx(), cfg) == Approved()


def test_per_trade_premium_cap_exceeded() -> None:
    cfg = RiskConfig()
    # 1 contract * 100 * $15 = $1500 -> 1363 EUR > 2% of 50k = 1000 EUR
    trade = _option_buy(1, _usd("15.00"))
    result = check_per_trade_premium_cap(trade, _eur(50_000), _fx(), cfg)
    assert isinstance(result, Rejected)
    assert "premium" in result.reason


def test_per_trade_premium_skipped_for_stock_or_sell() -> None:
    cfg = RiskConfig()
    stock = _stock_buy("AAPL", 100, _usd("10000"))  # huge but stock
    assert check_per_trade_premium_cap(stock, _eur(50_000), _fx(), cfg) == Approved()


# ------------------------------------------------- 6. total open premium
def test_total_open_premium_includes_proposed_trade() -> None:
    cfg = RiskConfig()
    # already open: 1 long call worth $4000 * 100 = $400k? -> way over.
    # Use 1 contract @ $4 last quote = $400 = ~363 EUR. Plus a new $200 trade.
    pos = Position(
        symbol="AAPL",
        asset_type="option",
        qty=1,
        avg_price=_usd("3.00"),
        expiry=date(2026, 6, 19),
        strike=_usd("200.00"),
        right="C",
    )
    portfolio = Portfolio(cash={"EUR": _eur(50_000)}, positions=(pos,))
    quotes = {"AAPL": _usd("4.00")}
    proposed = _option_buy(1, _usd("2.00"))  # +$200 = 181 EUR

    result = check_total_open_premium_cap(
        proposed, portfolio, quotes, _eur(50_000), _fx(), cfg
    )
    assert result == Approved()


def test_total_open_premium_breach_rejects() -> None:
    cfg = RiskConfig()
    # 50 open contracts * 100 * $20 = $100,000 = 90909 EUR -> >> 10% of 50k=5000 EUR
    pos = Position(
        symbol="AAPL",
        asset_type="option",
        qty=50,
        avg_price=_usd("20.00"),
        expiry=date(2026, 6, 19),
        strike=_usd("200.00"),
        right="C",
    )
    portfolio = Portfolio(cash={"EUR": _eur(50_000)}, positions=(pos,))
    quotes = {"AAPL": _usd("20.00")}
    proposed = _option_buy(1, _usd("1.00"))

    result = check_total_open_premium_cap(
        proposed, portfolio, quotes, _eur(50_000), _fx(), cfg
    )
    assert isinstance(result, Rejected)


# ------------------------------------------------- 7. single-name cap
def test_single_name_cap_within_limit() -> None:
    cfg = RiskConfig()
    portfolio = Portfolio(cash={"EUR": _eur(50_000)})
    # 30 shares * $150 = $4500 = 4090 EUR < 10% of 50k = 5000 EUR
    trade = _stock_buy("AAPL", 30, _usd("150.00"))
    assert (
        check_single_name_cap(
            trade, portfolio, quotes={}, equity_eur=_eur(50_000), fx=_fx(), config=cfg
        )
        == Approved()
    )


def test_single_name_cap_exceeded() -> None:
    cfg = RiskConfig()
    portfolio = Portfolio(cash={"EUR": _eur(50_000)})
    # 50 shares * $150 = $7500 = 6818 EUR > 5000 EUR cap
    trade = _stock_buy("AAPL", 50, _usd("150.00"))
    result = check_single_name_cap(trade, portfolio, {}, _eur(50_000), _fx(), cfg)
    assert isinstance(result, Rejected)
    assert "single-name" in result.reason


def test_single_name_cap_aggregates_existing_position() -> None:
    cfg = RiskConfig()
    pos = Position(symbol="AAPL", asset_type="stock", qty=20, avg_price=_usd("150.00"))
    portfolio = Portfolio(cash={"EUR": _eur(50_000)}, positions=(pos,))
    quotes = {"AAPL": _usd("150.00")}
    # existing: 20*150 = 3000 USD = 2727 EUR
    # new: 20*150 = 3000 USD = 2727 EUR
    # total: 5454 EUR > 5000 cap
    trade = _stock_buy("AAPL", 20, _usd("150.00"))
    result = check_single_name_cap(trade, portfolio, quotes, _eur(50_000), _fx(), cfg)
    assert isinstance(result, Rejected)


def test_single_name_cap_sells_always_pass() -> None:
    cfg = RiskConfig()
    portfolio = Portfolio(cash={"EUR": _eur(50_000)})
    trade = Trade(
        symbol="AAPL",
        asset_type="stock",
        side="SELL",
        qty=10000,  # absurd, but a sell — rule should not block on size
        price=_usd("150.00"),
        fees=_usd(0),
    )
    assert (
        check_single_name_cap(trade, portfolio, {}, _eur(50_000), _fx(), cfg)
        == Approved()
    )


# ------------------------------------------------- composer ordering
def test_risk_checker_returns_first_rejection() -> None:
    cfg = RiskConfig()
    checker = RiskChecker(cfg)
    portfolio = Portfolio(cash={"EUR": _eur(50_000)})

    inputs = RiskInputs(
        trade=_stock_buy("AAPL", 1, _usd(100)),
        portfolio=portfolio,
        quotes={},
        fx=_fx(),
        equity_eur=_eur(50_000),
        daily_pnl_pct=-0.05,  # already over the daily cutoff
        weekly_pnl_pct=0.0,
        now=_berlin(2026, 5, 1, 16, 0),
    )
    result = checker.check(inputs)
    assert isinstance(result, Rejected)
    assert "daily" in result.reason  # daily cutoff fires first


def test_risk_checker_approves_clean_trade() -> None:
    cfg = RiskConfig()
    checker = RiskChecker(cfg)
    portfolio = Portfolio(cash={"EUR": _eur(50_000)})

    inputs = RiskInputs(
        trade=_stock_buy("AAPL", 10, _usd("150.00")),
        portfolio=portfolio,
        quotes={},
        fx=_fx(),
        equity_eur=_eur(50_000),
        daily_pnl_pct=0.0,
        weekly_pnl_pct=0.0,
        now=_berlin(2026, 5, 1, 16, 0),
    )
    assert checker.check(inputs) == Approved()


def test_risk_checker_blocks_just_before_close() -> None:
    cfg = RiskConfig(cutoff_minutes_before_close=30)
    checker = RiskChecker(cfg)
    inputs = RiskInputs(
        trade=_stock_buy("AAPL", 1, _usd(100)),
        portfolio=Portfolio(cash={"EUR": _eur(50_000)}),
        quotes={},
        fx=_fx(),
        equity_eur=_eur(50_000),
        daily_pnl_pct=0.0,
        weekly_pnl_pct=0.0,
        now=_berlin(2026, 5, 1, 21, 31),  # last 29 min
    )
    result = checker.check(inputs)
    assert isinstance(result, Rejected)
    assert "close" in result.reason


def test_risk_checker_xetra_close_cutoff() -> None:
    cfg = RiskConfig()
    checker = RiskChecker(cfg)
    # Xetra closes 17:30; 17:01 is within 30-min cutoff
    inputs = RiskInputs(
        trade=_stock_buy("SAP.DE", 1, _eur(100)),
        portfolio=Portfolio(cash={"EUR": _eur(50_000)}),
        quotes={},
        fx=_fx(),
        equity_eur=_eur(50_000),
        daily_pnl_pct=0.0,
        weekly_pnl_pct=0.0,
        now=_berlin(2026, 5, 1, 17, 1),
    )
    result = checker.check(inputs)
    assert isinstance(result, Rejected)


# ------------------------------------------------- internal date helper
def test_session_close_dt_independence_of_trade_date() -> None:
    """Sanity: rule reads only the time-of-day fields, not the date."""
    trade = _stock_buy("AAPL", 1, _usd(100))
    a = check_session_hours(trade, _berlin(2026, 5, 1, 16, 0))
    b = check_session_hours(
        trade,
        _berlin(2026, 5, 1, 16, 0) + timedelta(days=7),  # also a Friday
    )
    assert a == b == Approved()
