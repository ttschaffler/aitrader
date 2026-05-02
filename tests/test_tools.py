"""Tool schemas exposed to Claude."""

from src.agent.tools import SETUPS, tool_schemas


def test_all_expected_tools_present() -> None:
    names = {t["name"] for t in tool_schemas()}
    assert names == {
        "get_quote",
        "get_option_chain",
        "get_news",
        "get_portfolio",
        "propose_trade",
        "skip_tick",
    }


def test_propose_trade_setup_enum_matches_constant() -> None:
    [propose] = [t for t in tool_schemas() if t["name"] == "propose_trade"]
    enum = propose["input_schema"]["properties"]["setup"]["enum"]
    assert tuple(enum) == SETUPS


def test_propose_trade_required_fields() -> None:
    [propose] = [t for t in tool_schemas() if t["name"] == "propose_trade"]
    required = set(propose["input_schema"]["required"])
    assert {
        "setup",
        "symbol",
        "side",
        "asset_type",
        "qty",
        "price",
        "currency",
        "rationale",
    } <= required


def test_skip_tick_requires_reason() -> None:
    [skip] = [t for t in tool_schemas() if t["name"] == "skip_tick"]
    assert skip["input_schema"]["required"] == ["reason"]


def test_get_news_lookback_bounded() -> None:
    [news] = [t for t in tool_schemas() if t["name"] == "get_news"]
    schema = news["input_schema"]["properties"]["lookback_hours"]
    assert schema["minimum"] == 1
    assert schema["maximum"] == 168
