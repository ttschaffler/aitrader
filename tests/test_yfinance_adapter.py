"""yfinance adapter: behavior with injected fakes (no network)."""

from datetime import UTC, date, datetime

import pytest
from src.data.yfinance_adapter import YFinanceQuoteSource
from src.depot.money import Money

_FROZEN_NOW = datetime(2026, 5, 1, 14, 0, tzinfo=UTC)


def _frozen_clock() -> datetime:
    return _FROZEN_NOW


def test_get_quote_builds_money_from_us_symbol() -> None:
    def fake_quote(symbol: str) -> dict[str, object]:
        assert symbol == "AAPL"
        return {
            "last_price": 150.25,
            "bid": 150.20,
            "ask": 150.30,
            "volume": 1_234_567,
            "currency": "USD",
        }

    source = YFinanceQuoteSource(fetch_quote_raw=fake_quote, clock=_frozen_clock)
    quote = source.get_quote("AAPL")

    assert quote.symbol == "AAPL"
    assert quote.price == Money.of("150.25", "USD")
    assert quote.bid == Money.of("150.20", "USD")
    assert quote.ask == Money.of("150.30", "USD")
    assert quote.volume == 1_234_567
    assert quote.as_of == _FROZEN_NOW


def test_get_quote_infers_eur_currency_for_de_suffix() -> None:
    def fake_quote(symbol: str) -> dict[str, object]:
        return {
            "last_price": 120.5,
            "bid": None,
            "ask": None,
            "volume": None,
            "currency": None,  # missing from yfinance
        }

    source = YFinanceQuoteSource(fetch_quote_raw=fake_quote, clock=_frozen_clock)
    quote = source.get_quote("SAP.DE")

    assert quote.price.currency == "EUR"
    assert quote.price == Money.of("120.50", "EUR")
    assert quote.bid is None and quote.ask is None and quote.volume is None


def test_get_quote_raises_when_no_last_price() -> None:
    def fake_quote(_symbol: str) -> dict[str, object]:
        return {"last_price": None}

    source = YFinanceQuoteSource(fetch_quote_raw=fake_quote, clock=_frozen_clock)
    with pytest.raises(ValueError, match="no last_price"):
        source.get_quote("AAPL")


def test_get_option_chain_builds_calls_and_puts() -> None:
    expiry = date(2026, 6, 19)

    def fake_chain(
        symbol: str, exp: date | None
    ) -> tuple[dict[str, list[dict[str, object]]], date]:
        assert symbol == "AAPL"
        assert exp == expiry
        return (
            {
                "calls": [
                    {
                        "strike": 200.0,
                        "lastPrice": 3.5,
                        "bid": 3.4,
                        "ask": 3.6,
                        "volume": 120,
                        "openInterest": 1_500,
                    },
                ],
                "puts": [
                    {
                        "strike": 200.0,
                        "lastPrice": 1.5,
                        "bid": 1.4,
                        "ask": 1.6,
                        "volume": 50,
                        "openInterest": 800,
                    },
                ],
            },
            expiry,
        )

    source = YFinanceQuoteSource(
        fetch_quote_raw=lambda _s: {"last_price": 1, "currency": "USD"},
        fetch_option_chain_raw=fake_chain,
        clock=_frozen_clock,
    )
    chain = source.get_option_chain("AAPL", expiry)

    assert {c.right for c in chain} == {"C", "P"}
    call = next(c for c in chain if c.right == "C")
    put = next(c for c in chain if c.right == "P")
    assert call.strike == Money.of("200.00", "USD")
    assert call.last == Money.of("3.50", "USD")
    assert call.open_interest == 1_500
    assert put.last == Money.of("1.50", "USD")
    assert put.expiry == expiry


def test_get_option_chain_handles_missing_optional_fields() -> None:
    expiry = date(2026, 6, 19)

    def fake_chain(
        _symbol: str, _exp: date | None
    ) -> tuple[dict[str, list[dict[str, object]]], date]:
        return (
            {
                "calls": [
                    {
                        "strike": 100.0,
                        "lastPrice": None,
                        "bid": None,
                        "ask": None,
                        "volume": None,
                        "openInterest": None,
                    }
                ],
                "puts": [],
            },
            expiry,
        )

    source = YFinanceQuoteSource(
        fetch_quote_raw=lambda _s: {"last_price": 1, "currency": "USD"},
        fetch_option_chain_raw=fake_chain,
        clock=_frozen_clock,
    )
    [contract] = source.get_option_chain("AAPL", expiry)
    assert contract.last is None
    assert contract.bid is None
    assert contract.volume is None
    assert contract.open_interest is None


def test_get_option_chain_missing_strike_raises() -> None:
    def fake_chain(
        _s: str, _e: date | None
    ) -> tuple[dict[str, list[dict[str, object]]], date]:
        return ({"calls": [{"strike": None}], "puts": []}, date(2026, 6, 19))

    source = YFinanceQuoteSource(
        fetch_quote_raw=lambda _s: {"last_price": 1, "currency": "USD"},
        fetch_option_chain_raw=fake_chain,
        clock=_frozen_clock,
    )
    with pytest.raises(ValueError, match="missing strike"):
        source.get_option_chain("AAPL", date(2026, 6, 19))
