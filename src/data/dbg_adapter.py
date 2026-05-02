"""Deutsche Börse API Platform: Eurex Reference Data (GraphQL).

Provides product / instrument reference data (DAX futures, options
expiries and strike ladders, contract specs). Reference data is
**daily-cached on disk** to stay well under the portal's rate limits.

The HTTP transport is injected so unit tests don't touch the network.
Live integration tests live under ``tests/integration/``.

The exact GraphQL schema offered by the portal is subject to change;
queries here target the documented field names and parsing is defensive
about missing optional fields. Adjust ``_QUERY_*`` once a real key has
been used to pin the schema.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Protocol

from src.depot.money import Money

OptionRight = Literal["C", "P"]
ProductType = Literal["FUTURE", "OPTION"]


@dataclass(frozen=True, slots=True)
class DBGProduct:
    product_id: str
    name: str
    product_type: ProductType
    underlying_symbol: str
    currency: str


@dataclass(frozen=True, slots=True)
class DBGInstrument:
    product_id: str
    expiry: date
    strike: Money | None
    right: OptionRight | None


class GraphQLTransport(Protocol):
    """Tiny role-specific transport for one GraphQL POST."""

    def request(self, query: str, variables: dict[str, Any]) -> dict[str, Any]: ...


_QUERY_PRODUCT = """
query GetProduct($id: String!) {
  product(id: $id) {
    productId
    name
    productType
    underlyingSymbol
    currency
  }
}
""".strip()

_QUERY_INSTRUMENTS = """
query GetInstruments($productId: String!, $expiry: String) {
  instruments(productId: $productId, expiry: $expiry) {
    productId
    expiry
    strike
    callPut
  }
}
""".strip()


class _RateLimited(Exception):
    """Raised by transports to signal HTTP 429."""


def _to_right(value: str | None) -> OptionRight | None:
    if value is None:
        return None
    upper = value.upper()
    if upper in ("C", "CALL"):
        return "C"
    if upper in ("P", "PUT"):
        return "P"
    raise ValueError(f"unknown option right value: {value!r}")


def _to_product_type(value: str) -> ProductType:
    upper = value.upper()
    if upper not in ("FUTURE", "OPTION"):
        raise ValueError(f"unknown DBG product type: {value!r}")
    return "FUTURE" if upper == "FUTURE" else "OPTION"


class EurexReferenceDataClient:
    """Eurex T7 reference data client with on-disk daily caching.

    SOLID: this class owns network + cache I/O only. Parsing into the
    DBGProduct / DBGInstrument value objects is the second responsibility
    but kept narrow (single source of truth for the GraphQL field names).
    """

    DEFAULT_BASE_URL = (
        "https://api.developer.deutsche-boerse.com/"
        "prod/accesstot7-referencedata/1.1.0/"
    )

    def __init__(
        self,
        transport: GraphQLTransport,
        cache_dir: Path | str | None = None,
        today_provider: Callable[[], date] = date.today,
        max_retries: int = 4,
        backoff_base: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._transport = transport
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._today = today_provider
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._sleep = sleep

    # ----------------------------------------------------------- public API
    def get_product(self, product_id: str) -> DBGProduct:
        cached = self._read_cache("product", product_id)
        if cached is None:
            cached = self._request_with_backoff(
                _QUERY_PRODUCT, {"id": product_id}
            )
            self._write_cache("product", product_id, cached)
        node = cached.get("data", {}).get("product")
        if not node:
            raise ValueError(f"DBG product not found: {product_id}")
        return DBGProduct(
            product_id=node["productId"],
            name=node["name"],
            product_type=_to_product_type(node["productType"]),
            underlying_symbol=node["underlyingSymbol"],
            currency=node.get("currency", "EUR"),
        )

    def get_instruments(
        self, product_id: str, expiry: date | None = None
    ) -> list[DBGInstrument]:
        cache_key = (
            f"{product_id}-{expiry.isoformat()}" if expiry else f"{product_id}-all"
        )
        cached = self._read_cache("instruments", cache_key)
        if cached is None:
            variables: dict[str, Any] = {"productId": product_id}
            if expiry is not None:
                variables["expiry"] = expiry.isoformat()
            cached = self._request_with_backoff(_QUERY_INSTRUMENTS, variables)
            self._write_cache("instruments", cache_key, cached)

        rows = cached.get("data", {}).get("instruments") or []
        product_currency = self._product_currency_hint(product_id) or "EUR"
        return [self._parse_instrument(row, product_currency) for row in rows]

    # ----------------------------------------------------------- internals
    def _product_currency_hint(self, product_id: str) -> str | None:
        """Best-effort currency lookup from a previously cached product."""
        if self._cache_dir is None:
            return None
        path = self._cache_path("product", product_id)
        if not path.exists():
            return None
        node = json.loads(path.read_text(encoding="utf-8")).get("data", {}).get(
            "product"
        )
        if not node:
            return None
        currency = node.get("currency")
        return str(currency) if currency else None

    @staticmethod
    def _parse_instrument(row: dict[str, Any], currency: str) -> DBGInstrument:
        strike_raw = row.get("strike")
        strike = (
            Money.of(Decimal(str(strike_raw)), currency)
            if strike_raw is not None
            else None
        )
        return DBGInstrument(
            product_id=row["productId"],
            expiry=date.fromisoformat(row["expiry"]),
            strike=strike,
            right=_to_right(row.get("callPut")),
        )

    def _request_with_backoff(
        self, query: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        attempt = 0
        while True:
            try:
                return self._transport.request(query, variables)
            except _RateLimited:
                attempt += 1
                if attempt > self._max_retries:
                    raise
                self._sleep(self._backoff_base * (2 ** (attempt - 1)))

    # ----------------------------------------------------------- cache I/O
    def _cache_path(self, namespace: str, key: str) -> Path:
        if self._cache_dir is None:
            raise RuntimeError("cache_dir not configured")
        day = self._today().isoformat()
        return self._cache_dir / day / namespace / f"{key}.json"

    def _read_cache(self, namespace: str, key: str) -> dict[str, Any] | None:
        if self._cache_dir is None:
            return None
        path = self._cache_path(namespace, key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]

    def _write_cache(
        self, namespace: str, key: str, payload: dict[str, Any]
    ) -> None:
        if self._cache_dir is None:
            return
        path = self._cache_path(namespace, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


# ----------------------------------------------------------------- httpx
class HttpxGraphQLTransport:  # pragma: no cover - thin I/O shim
    """Production transport that POSTs to the Deutsche Börse portal.

    Lives here so a single import path covers both the client and its
    default transport.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = EurexReferenceDataClient.DEFAULT_BASE_URL,
        timeout_s: float = 30.0,
    ) -> None:
        import httpx

        self._client = httpx.Client(
            base_url=base_url,
            headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
            timeout=timeout_s,
        )

    def request(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        import httpx

        response = self._client.post(
            "graphql", json={"query": query, "variables": variables}
        )
        if response.status_code == 429:
            raise _RateLimited(response.text)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError(f"unexpected GraphQL response shape: {type(body)}")
        return body

    def close(self) -> None:
        self._client.close()


__all__ = [
    "DBGInstrument",
    "DBGProduct",
    "EurexReferenceDataClient",
    "GraphQLTransport",
    "HttpxGraphQLTransport",
]
