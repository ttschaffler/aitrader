"""Tool schemas exposed to Claude.

The LLM can ONLY emit a trade via ``propose_trade`` and may only choose
one of the six setups defined in CLAUDE.md / the system prompt. Anything
off-menu fails JSON-schema validation upstream.
"""

from __future__ import annotations

from typing import Any

SETUPS: tuple[str, ...] = (
    "long_stock",
    "close_stock",
    "long_call_or_put",
    "covered_call",
    "cash_secured_put",
)


def tool_schemas() -> list[dict[str, Any]]:
    """Return the tool definitions in Anthropic format."""
    return [
        {
            "name": "get_quote",
            "description": (
                "Latest price/bid/ask/volume for a US or DE equity symbol. "
                "Use yfinance-style symbols (e.g. 'AAPL', 'SAP.DE')."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
        },
        {
            "name": "get_option_chain",
            "description": (
                "US listed option chain for an underlying. Provide ISO "
                "expiry YYYY-MM-DD; nearest expiry is used if omitted."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "underlying": {"type": "string"},
                    "expiry": {"type": "string"},
                },
                "required": ["underlying"],
            },
        },
        {
            "name": "get_news",
            "description": (
                "Recent news for a symbol within the lookback window in hours."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "lookback_hours": {"type": "integer", "minimum": 1, "maximum": 168},
                },
                "required": ["symbol"],
            },
        },
        {
            "name": "get_portfolio",
            "description": (
                "Current cash by currency, open positions, and total equity in EUR."
            ),
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "propose_trade",
            "description": (
                "Submit a virtual trade proposal. Must select a setup from the menu. "
                "Option fields (expiry, strike, right) are required for option setups."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "setup": {"type": "string", "enum": list(SETUPS)},
                    "symbol": {"type": "string"},
                    "side": {"type": "string", "enum": ["BUY", "SELL"]},
                    "asset_type": {"type": "string", "enum": ["stock", "option"]},
                    "qty": {"type": "integer", "minimum": 1},
                    "price": {"type": "number", "minimum": 0},
                    "currency": {"type": "string"},
                    "fees": {"type": "number", "minimum": 0, "default": 0},
                    "expiry": {"type": "string"},
                    "strike": {"type": "number"},
                    "right": {"type": "string", "enum": ["C", "P"]},
                    "rationale": {"type": "string", "minLength": 10},
                },
                "required": [
                    "setup",
                    "symbol",
                    "side",
                    "asset_type",
                    "qty",
                    "price",
                    "currency",
                    "rationale",
                ],
            },
        },
        {
            "name": "skip_tick",
            "description": "Skip this tick. Provide a brief reason.",
            "input_schema": {
                "type": "object",
                "properties": {"reason": {"type": "string", "minLength": 5}},
                "required": ["reason"],
            },
        },
    ]
