"""Quotes and US option chains via yfinance.

Wraps yfinance behind two injectable callables (``fetch_quote_raw`` and
``fetch_option_chain_raw``) so tests can supply fakes without importing
``yfinance``. Live integration tests live under ``tests/integration``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from src.data.interfaces import OptionContract, OptionRight, Quote
from src.depot.money import Money

RawQuote = dict[str, Any]
RawOptionRow = dict[str, Any]
RawOptionChain = dict[str, list[RawOptionRow]]  # {"calls": [...], "puts": [...]}


def _currency_for_symbol(symbol: str) -> str:
    return "EUR" if symbol.upper().endswith(".DE") else "USD"


def _default_fetch_quote_raw(symbol: str) -> RawQuote:  # pragma: no cover - I/O
    import yfinance as yf

    info = yf.Ticker(symbol).fast_info
    get = info.get if hasattr(info, "get") else lambda key, default=None: default
    return {
        "last_price": get("last_price"),
        "bid": get("bid"),
        "ask": get("ask"),
        "volume": get("last_volume"),
        "currency": get("currency"),
    }


def _default_fetch_option_chain_raw(  # pragma: no cover - I/O
    symbol: str, expiry: date | None
) -> tuple[RawOptionChain, date]:
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    available: list[str] = list(ticker.options)
    if not available:
        return ({"calls": [], "puts": []}, expiry or date.today())

    chosen = expiry.isoformat() if expiry else available[0]
    chain = ticker.option_chain(chosen)
    return (
        {
            "calls": chain.calls.to_dict("records"),
            "puts": chain.puts.to_dict("records"),
        },
        date.fromisoformat(chosen),
    )


def _money_from_raw(value: Any, currency: str) -> Money | None:
    if value is None:
        return None
    return Money.of(Decimal(str(value)), currency)


class YFinanceQuoteSource:
    """Implements ``QuoteSource`` and ``OptionChainSource``.

    See ``src.data.interfaces``. yfinance is reached through the two
    injected callables; ``__init__`` does no I/O.
    """

    def __init__(
        self,
        fetch_quote_raw: Callable[[str], RawQuote] = _default_fetch_quote_raw,
        fetch_option_chain_raw: Callable[
            [str, date | None], tuple[RawOptionChain, date]
        ] = _default_fetch_option_chain_raw,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._fetch_quote_raw = fetch_quote_raw
        self._fetch_option_chain_raw = fetch_option_chain_raw
        self._clock = clock

    def get_quote(self, symbol: str) -> Quote:
        raw = self._fetch_quote_raw(symbol)
        last = raw.get("last_price")
        if last is None:
            raise ValueError(f"yfinance returned no last_price for {symbol}")

        currency = (raw.get("currency") or _currency_for_symbol(symbol)).upper()
        price = Money.of(Decimal(str(last)), currency)
        bid = _money_from_raw(raw.get("bid"), currency)
        ask = _money_from_raw(raw.get("ask"), currency)
        volume_raw = raw.get("volume")
        volume = int(volume_raw) if volume_raw is not None else None
        return Quote(
            symbol=symbol,
            price=price,
            bid=bid,
            ask=ask,
            volume=volume,
            as_of=self._clock(),
        )

    def get_option_chain(
        self, underlying: str, expiry: date | None = None
    ) -> list[OptionContract]:
        raw, resolved_expiry = self._fetch_option_chain_raw(underlying, expiry)
        currency = _currency_for_symbol(underlying)
        contracts: list[OptionContract] = []
        labelled: tuple[tuple[str, OptionRight], ...] = (("calls", "C"), ("puts", "P"))
        for right_label, right in labelled:
            for row in raw.get(right_label, []):
                contracts.append(
                    self._row_to_contract(
                        row, underlying, resolved_expiry, currency, right
                    )
                )
        return contracts

    @staticmethod
    def _row_to_contract(
        row: RawOptionRow,
        underlying: str,
        expiry: date,
        currency: str,
        right: OptionRight,
    ) -> OptionContract:
        strike_raw = row.get("strike")
        if strike_raw is None:
            raise ValueError(f"option row missing strike for {underlying}")
        strike = Money.of(Decimal(str(strike_raw)), currency)
        oi_raw = row.get("openInterest")
        vol_raw = row.get("volume")
        return OptionContract(
            underlying=underlying,
            expiry=expiry,
            strike=strike,
            right=right,
            last=_money_from_raw(row.get("lastPrice"), currency),
            bid=_money_from_raw(row.get("bid"), currency),
            ask=_money_from_raw(row.get("ask"), currency),
            volume=int(vol_raw) if vol_raw is not None else None,
            open_interest=int(oi_raw) if oi_raw is not None else None,
        )
