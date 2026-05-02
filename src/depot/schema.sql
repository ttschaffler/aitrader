-- Virtual depot schema. All money columns are integer minor units (cents).
-- This file is the single source of truth for the SQLite layout.

CREATE TABLE IF NOT EXISTS cash (
    currency      TEXT    PRIMARY KEY,
    balance_minor INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT    NOT NULL,
    asset_type      TEXT    NOT NULL CHECK (asset_type IN ('stock', 'option')),
    qty             INTEGER NOT NULL,
    avg_price_minor INTEGER NOT NULL,
    currency        TEXT    NOT NULL,
    expiry          TEXT,                                 -- YYYY-MM-DD, NULL for stock
    strike_minor    INTEGER,
    right           TEXT    CHECK (right IN ('C', 'P')),  -- NULL for stock
    UNIQUE (symbol, asset_type, expiry, strike_minor, right)
);

CREATE TABLE IF NOT EXISTS trades (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT    NOT NULL,                         -- ISO 8601
    symbol       TEXT    NOT NULL,
    side         TEXT    NOT NULL CHECK (side IN ('BUY', 'SELL')),
    asset_type   TEXT    NOT NULL CHECK (asset_type IN ('stock', 'option')),
    qty          INTEGER NOT NULL,
    price_minor  INTEGER NOT NULL,
    currency     TEXT    NOT NULL,
    fees_minor   INTEGER NOT NULL DEFAULT 0,
    fx_rate      REAL,
    expiry       TEXT,
    strike_minor INTEGER,
    right        TEXT    CHECK (right IN ('C', 'P')),
    rationale    TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
    ts                   TEXT    PRIMARY KEY,              -- ISO 8601
    equity_eur_minor     INTEGER NOT NULL,
    cash_eur_minor       INTEGER NOT NULL,
    exposure_eur_minor   INTEGER NOT NULL,
    unrealized_pnl_minor INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist (
    symbol TEXT PRIMARY KEY,
    notes  TEXT
);
