"""Composition root: notifier selection and wiring assembly."""

from __future__ import annotations

from typing import Any

from src.agent.llm import LLMResult, ToolHandler
from src.config import (
    AnthropicSettings,
    DBGSettings,
    DepotSettings,
    FinnhubSettings,
    LoggingSettings,
    RiskSettings,
    ScheduleSettings,
    Settings,
    SmtpSettings,
    WatchlistSettings,
)
from src.notify.console_notifier import ConsoleNotifier
from src.notify.smtp_notifier import SmtpNotifier
from src.scheduler import build_notifier, build_wiring


def _settings(*, smtp_host: str = "") -> Settings:
    return Settings(
        depot=DepotSettings("EUR", 50_000, 100_000),
        risk=RiskSettings(0.10, 0.10, 0.02, -0.03, -0.08, 30),
        schedule=ScheduleSettings("Europe/Berlin", 20, 20, "sunday", "19:00", "22:15"),
        watchlist=WatchlistSettings(("AAPL",), ("SAP.DE",)),
        anthropic=AnthropicSettings(
            api_key="k",
            model_intraday="claude-sonnet-4-6",
            model_weekly="claude-opus-4-7",
            prompt_cache=True,
        ),
        finnhub=FinnhubSettings("k"),
        dbg=DBGSettings("k", "https://example.com/", "data/cache/dbg"),
        smtp=SmtpSettings(
            host=smtp_host,
            port=587,
            username="u" if smtp_host else "",
            password="p" if smtp_host else "",
            from_address="f@e.com" if smtp_host else "",
            to_address="t@e.com" if smtp_host else "",
        ),
        logging=LoggingSettings("INFO", True),
    )


class _NoopLLM:
    def run_tool_use_loop(
        self,
        *,
        model: str,
        system_blocks: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        initial_user_message: str,
        tool_handler: ToolHandler,
        max_iterations: int = 10,
        max_tokens: int = 2048,
    ) -> LLMResult:
        return LLMResult(final_text="", tool_calls=())  # type: ignore[arg-type]


def test_build_notifier_falls_back_to_console_when_smtp_blank() -> None:
    notifier = build_notifier(_settings(smtp_host=""))
    assert isinstance(notifier, ConsoleNotifier)


def test_build_notifier_returns_smtp_when_configured() -> None:
    notifier = build_notifier(_settings(smtp_host="smtp.example.com"))
    assert isinstance(notifier, SmtpNotifier)


def test_build_wiring_assembles_full_trader(tmp_path: Any) -> None:
    db_path = tmp_path / "depot.sqlite"
    wiring = build_wiring(
        _settings(),
        db_path=db_path,
        llm_client_factory=lambda _s: _NoopLLM(),  # type: ignore[arg-type,return-value]
    )

    assert wiring.trader.watchlist == ("AAPL", "SAP.DE")
    assert wiring.trader.model == "claude-sonnet-4-6"
    assert wiring.trader.recorder is wiring.repo
    # Goal flows through to trader
    from src.depot.money import Money

    assert wiring.trader.goal_eur == Money.of(100_000, "EUR")


def test_build_wiring_uses_settings_risk_thresholds(tmp_path: Any) -> None:
    settings = _settings()
    wiring = build_wiring(
        settings,
        db_path=tmp_path / "depot.sqlite",
        llm_client_factory=lambda _s: _NoopLLM(),  # type: ignore[arg-type,return-value]
    )
    cfg = wiring.trader.risk.config
    assert cfg.max_single_name_pct == settings.risk.max_single_name_pct
    assert cfg.daily_loss_cutoff_pct == settings.risk.daily_loss_cutoff_pct
