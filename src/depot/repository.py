"""SQLite persistence for the virtual depot.

This is the only module in ``src.depot`` that performs I/O. The pure
domain (``portfolio.py``) does the math; this module reads and writes
state.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from types import TracebackType
from typing import Self, cast

from src.depot.money import Money
from src.depot.portfolio import Portfolio, Position, Right, Trade

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _to_right(value: str | None) -> Right | None:
    if value is None:
        return None
    if value not in ("C", "P"):
        raise ValueError(f"invalid right column value: {value!r}")
    return cast(Right, value)


class SQLiteDepotRepository:
    """Read/write the virtual depot.

    One reason to change: the SQL layer. Schema is bootstrapped from
    ``schema.sql`` on construction.
    """

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    def _init_schema(self) -> None:
        ddl = _SCHEMA_PATH.read_text(encoding="utf-8")
        with self._conn:
            self._conn.executescript(ddl)

    # ------------------------------------------------------------------ cash
    def load_portfolio(self) -> Portfolio:
        cash: dict[str, Money] = {}
        for row in self._conn.execute("SELECT currency, balance_minor FROM cash"):
            cash[row["currency"]] = Money(row["balance_minor"], row["currency"])

        positions: list[Position] = []
        for row in self._conn.execute(
            "SELECT symbol, asset_type, qty, avg_price_minor, currency, "
            "expiry, strike_minor, right FROM positions"
        ):
            expiry = date.fromisoformat(row["expiry"]) if row["expiry"] else None
            strike = (
                Money(row["strike_minor"], row["currency"])
                if row["strike_minor"] is not None
                else None
            )
            positions.append(
                Position(
                    symbol=row["symbol"],
                    asset_type=row["asset_type"],
                    qty=row["qty"],
                    avg_price=Money(row["avg_price_minor"], row["currency"]),
                    expiry=expiry,
                    strike=strike,
                    right=_to_right(row["right"]),
                )
            )
        return Portfolio(cash=cash, positions=tuple(positions))

    def save_portfolio(self, portfolio: Portfolio) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM cash")
            self._conn.execute("DELETE FROM positions")
            self._conn.executemany(
                "INSERT INTO cash(currency, balance_minor) VALUES (?, ?)",
                [(c, m.minor) for c, m in portfolio.cash.items()],
            )
            self._conn.executemany(
                "INSERT INTO positions("
                "symbol, asset_type, qty, avg_price_minor, currency, "
                "expiry, strike_minor, right) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        p.symbol,
                        p.asset_type,
                        p.qty,
                        p.avg_price.minor,
                        p.avg_price.currency,
                        p.expiry.isoformat() if p.expiry else None,
                        p.strike.minor if p.strike else None,
                        p.right,
                    )
                    for p in portfolio.positions
                ],
            )

    # ---------------------------------------------------------------- trades
    def record_trade(
        self,
        trade: Trade,
        *,
        ts: datetime,
        rationale: str | None = None,
        fx_rate: float | None = None,
    ) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO trades("
                "ts, symbol, side, asset_type, qty, price_minor, currency, "
                "fees_minor, fx_rate, expiry, strike_minor, right, rationale) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ts.isoformat(),
                    trade.symbol,
                    trade.side,
                    trade.asset_type,
                    trade.qty,
                    trade.price.minor,
                    trade.price.currency,
                    trade.fees.minor,
                    fx_rate,
                    trade.expiry.isoformat() if trade.expiry else None,
                    trade.strike.minor if trade.strike else None,
                    trade.right,
                    rationale,
                ),
            )

    def trade_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM trades").fetchone()
        count = row["n"]
        assert isinstance(count, int)
        return count

    # ------------------------------------------------------------- watchlist
    def add_to_watchlist(self, symbol: str, notes: str | None = None) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO watchlist(symbol, notes) VALUES (?, ?)",
                (symbol, notes),
            )

    def watchlist(self) -> list[str]:
        return [
            row["symbol"]
            for row in self._conn.execute(
                "SELECT symbol FROM watchlist ORDER BY symbol"
            )
        ]
