"""DBG Eurex Reference Data client: parsing, daily cache, 429 backoff."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from src.data.dbg_adapter import (
    DBGInstrument,
    DBGProduct,
    EurexReferenceDataClient,
    _RateLimited,
)
from src.depot.money import Money


class _RecordingTransport:
    """Records calls and returns a queue of canned responses."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def request(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((query, dict(variables)))
        if not self.responses:
            raise AssertionError("no more canned responses queued")
        return self.responses.pop(0)


class _RaisingTransport:
    """Raises 429 N times, then succeeds."""

    def __init__(self, fail_times: int, success: dict[str, Any]) -> None:
        self.fail_times = fail_times
        self.success = success
        self.attempts = 0

    def request(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise _RateLimited("429 rate limited")
        return self.success


def _product_response() -> dict[str, Any]:
    return {
        "data": {
            "product": {
                "productId": "FDAX",
                "name": "DAX Future",
                "productType": "FUTURE",
                "underlyingSymbol": "DAX",
                "currency": "EUR",
            }
        }
    }


def _instrument_response() -> dict[str, Any]:
    return {
        "data": {
            "instruments": [
                {
                    "productId": "ODAX",
                    "expiry": "2026-06-19",
                    "strike": 18000.0,
                    "callPut": "CALL",
                },
                {
                    "productId": "ODAX",
                    "expiry": "2026-06-19",
                    "strike": 18000.0,
                    "callPut": "PUT",
                },
            ]
        }
    }


def test_get_product_parses_response() -> None:
    transport = _RecordingTransport([_product_response()])
    client = EurexReferenceDataClient(transport)

    product = client.get_product("FDAX")

    assert product == DBGProduct(
        product_id="FDAX",
        name="DAX Future",
        product_type="FUTURE",
        underlying_symbol="DAX",
        currency="EUR",
    )
    assert len(transport.calls) == 1
    assert transport.calls[0][1] == {"id": "FDAX"}


def test_get_product_missing_raises() -> None:
    transport = _RecordingTransport([{"data": {"product": None}}])
    client = EurexReferenceDataClient(transport)

    with pytest.raises(ValueError, match="not found"):
        client.get_product("ZZZZ")


def test_get_instruments_parses_strike_currency_and_right(
    tmp_path: Path,
) -> None:
    transport = _RecordingTransport([_product_response(), _instrument_response()])
    client = EurexReferenceDataClient(transport, cache_dir=tmp_path)

    # warm the product cache so the instrument call can find a currency hint
    client.get_product("FDAX")
    instruments = client.get_instruments("ODAX", date(2026, 6, 19))

    assert len(instruments) == 2
    assert all(isinstance(i, DBGInstrument) for i in instruments)
    call, put = instruments
    assert call.right == "C"
    assert put.right == "P"
    assert call.strike == Money.of("18000.00", "EUR")


def test_cache_round_trip_skips_transport_on_second_call(
    tmp_path: Path,
) -> None:
    transport = _RecordingTransport([_product_response()])
    client = EurexReferenceDataClient(transport, cache_dir=tmp_path)

    first = client.get_product("FDAX")
    second = client.get_product("FDAX")

    assert first == second
    assert len(transport.calls) == 1  # cache served the second call

    cache_files = list(tmp_path.rglob("*.json"))
    assert len(cache_files) == 1


def test_cache_keyed_per_day(tmp_path: Path) -> None:
    days = [date(2026, 5, 1), date(2026, 5, 2)]

    def today() -> date:
        return days[client_call_count[0]]

    client_call_count = [0]
    transport = _RecordingTransport([_product_response(), _product_response()])
    client = EurexReferenceDataClient(
        transport, cache_dir=tmp_path, today_provider=today
    )

    client.get_product("FDAX")
    client_call_count[0] = 1
    client.get_product("FDAX")  # different day -> new cache entry

    assert len(transport.calls) == 2
    assert (tmp_path / "2026-05-01" / "product" / "FDAX.json").exists()
    assert (tmp_path / "2026-05-02" / "product" / "FDAX.json").exists()


def test_429_triggers_exponential_backoff_then_succeeds() -> None:
    sleeps: list[float] = []
    transport = _RaisingTransport(fail_times=3, success=_product_response())
    client = EurexReferenceDataClient(
        transport,
        max_retries=4,
        backoff_base=0.5,
        sleep=sleeps.append,
    )

    product = client.get_product("FDAX")

    assert product.product_id == "FDAX"
    # 3 sleeps: 0.5, 1.0, 2.0 (base * 2^(attempt-1))
    assert sleeps == [0.5, 1.0, 2.0]
    assert transport.attempts == 4


def test_429_exceeding_max_retries_re_raises() -> None:
    transport = _RaisingTransport(fail_times=10, success=_product_response())
    client = EurexReferenceDataClient(
        transport, max_retries=2, backoff_base=0.0, sleep=lambda _s: None
    )

    with pytest.raises(_RateLimited):
        client.get_product("FDAX")
