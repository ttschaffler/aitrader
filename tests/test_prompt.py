"""System prompt: structure, watchlist embedding, cache marker."""

from src.agent.prompt import build_system_blocks


def test_returns_single_text_block_with_cache_marker_by_default() -> None:
    [block] = build_system_blocks(["AAPL", "SAP.DE"])

    assert block["type"] == "text"
    assert block["cache_control"] == {"type": "ephemeral"}


def test_watchlist_appears_in_text() -> None:
    [block] = build_system_blocks(["AAPL", "SAP.DE"], mark_cache=False)

    assert "- AAPL" in block["text"]
    assert "- SAP.DE" in block["text"]
    assert "Watchlist" in block["text"]


def test_strategy_menu_present_in_prompt() -> None:
    [block] = build_system_blocks(["AAPL"])
    text = block["text"]

    for setup in (
        "long_stock",
        "close_stock",
        "long_call_or_put",
        "covered_call",
        "cash_secured_put",
    ):
        assert setup in text


def test_risk_limits_present_in_prompt() -> None:
    [block] = build_system_blocks(["AAPL"])
    text = block["text"]

    assert "10%" in text  # single-name + total premium caps
    assert "2%" in text  # per-trade premium
    assert "-3%" in text  # daily cutoff
    assert "-8%" in text  # weekly cutoff


def test_disable_cache_marker() -> None:
    [block] = build_system_blocks(["AAPL"], mark_cache=False)
    assert "cache_control" not in block
