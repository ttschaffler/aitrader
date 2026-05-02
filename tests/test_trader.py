"""Trader orchestration: end-to-end with fakes for every dependency."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from src.agent.llm import LLMResult, ToolCallRecord, ToolHandler
from src.agent.risk import RiskChecker, RiskConfig
from src.agent.trader import TickContext, Trader
from src.data.fx import FxRate, FxRates
from src.data.interfaces import NewsItem, OptionContract, Quote
from src.depot.money import Money
from src.depot.portfolio import Portfolio
from src.depot.repository import SQLiteDepotRepository
from src.notify.console_notifier import ConsoleNotifier


def _eur(amount: int | str) -> Money:
    return Money.of(amount, "EUR")


def _usd(amount: int | str) -> Money:
    return Money.of(amount, "USD")


def _fx() -> FxRates:
    return FxRates.from_iterable(
        [FxRate("EUR", "USD", Decimal("1.10"), date(2026, 5, 1))]
    )


def _now() -> datetime:
    # Monday 16:00 Berlin (= US session, well clear of close cutoff)
    from zoneinfo import ZoneInfo

    return datetime(2026, 5, 4, 16, 0, tzinfo=ZoneInfo("Europe/Berlin")).astimezone(UTC)


# --------------------------------------------------------------- fake quote source
@dataclass
class _FakeQuoteSource:
    canned: dict[str, Money] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def get_quote(self, symbol: str) -> Quote:
        self.calls.append(symbol)
        price = self.canned.get(symbol, _usd("150.00"))
        return Quote(
            symbol=symbol, price=price, bid=None, ask=None, volume=None, as_of=_now()
        )


@dataclass
class _FakeOptionSource:
    def get_option_chain(
        self, underlying: str, expiry: date | None = None
    ) -> list[OptionContract]:
        return [
            OptionContract(
                underlying=underlying,
                expiry=expiry or date(2026, 6, 19),
                strike=_usd("200.00"),
                right="C",
                last=_usd("3.50"),
                bid=None,
                ask=None,
                volume=None,
                open_interest=None,
            )
        ]


@dataclass
class _FakeNewsSource:
    def get_news(self, symbol: str, lookback_hours: int) -> list[NewsItem]:
        return [
            NewsItem(
                symbol=symbol,
                headline="placeholder",
                summary="",
                source="test",
                published_at=_now(),
                url="https://example.com",
            )
        ]


# --------------------------------------------------------------- scripted LLM
@dataclass
class _ScriptedLLM:
    """Replays a list of (tool_name, tool_input) calls, then returns final text."""

    script: list[tuple[str, dict[str, Any]]]
    final_text: str = "done"

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
        records: list[ToolCallRecord] = []
        for name, input_ in self.script:
            result = tool_handler.handle(name, input_)
            records.append(ToolCallRecord(name, dict(input_), result))
        return LLMResult(
            final_text=self.final_text,
            tool_calls=tuple(records),
            iterations=len(self.script) + 1,
        )


# ---------------------------------------------------------------- helpers
def _build_trader(
    repo: SQLiteDepotRepository,
    llm: _ScriptedLLM,
    notifier: ConsoleNotifier | None = None,
    risk_config: RiskConfig | None = None,
    quotes: dict[str, Money] | None = None,
) -> Trader:
    return Trader(
        quotes=_FakeQuoteSource(canned=quotes or {"AAPL": _usd("150.00")}),
        options=_FakeOptionSource(),
        news=_FakeNewsSource(),
        notifier=notifier or ConsoleNotifier(),
        recorder=repo,
        risk=RiskChecker(risk_config or RiskConfig()),
        llm=llm,
        watchlist=("AAPL", "SAP.DE"),
        model="claude-sonnet-4-6",
    )


def _seeded_repo() -> SQLiteDepotRepository:
    repo = SQLiteDepotRepository()
    repo.save_portfolio(Portfolio(cash={"EUR": _eur(50_000)}))
    return repo


def _context(repo: SQLiteDepotRepository, **overrides: Any) -> TickContext:
    portfolio = repo.load_portfolio()
    base = TickContext(
        now=_now(),
        portfolio=portfolio,
        quotes={"AAPL": _usd("150.00")},
        fx=_fx(),
        equity_eur=_eur(50_000),
        daily_pnl_pct=0.0,
        weekly_pnl_pct=0.0,
        goal_eur=_eur(100_000),
    )
    for k, v in overrides.items():
        base = type(base)(**{**base.__dict__, k: v})
    return base


# ------------------------------------------------------------------- tests
def test_skip_tick_records_skip_outcome() -> None:
    repo = _seeded_repo()
    llm = _ScriptedLLM(script=[("skip_tick", {"reason": "low conviction"})])
    trader = _build_trader(repo, llm)

    outcome = trader.run_tick(_context(repo))

    assert outcome.kind == "skipped"
    assert "low conviction" in outcome.detail
    assert repo.load_portfolio().cash_in("EUR") == _eur(50_000)
    assert repo.trade_count() == 0


def test_propose_trade_approved_records_and_emails() -> None:
    repo = _seeded_repo()
    notifier = ConsoleNotifier()
    propose = (
        "propose_trade",
        {
            "setup": "long_stock",
            "symbol": "AAPL",
            "side": "BUY",
            "asset_type": "stock",
            "qty": 10,
            "price": 150.0,
            "currency": "USD",
            "fees": 1.0,
            "rationale": "earnings beat catalyst",
        },
    )
    llm = _ScriptedLLM(script=[propose])
    trader = _build_trader(repo, llm, notifier=notifier)

    outcome = trader.run_tick(_context(repo))

    assert outcome.kind == "recorded"
    portfolio = repo.load_portfolio()
    assert len(portfolio.positions) == 1
    assert portfolio.positions[0].symbol == "AAPL"
    assert repo.trade_count() == 1

    [sent] = notifier.sent
    assert sent.kind == "trade"
    assert "BUY 10 AAPL" in sent.subject


def test_propose_trade_rejected_by_risk_does_not_record() -> None:
    repo = _seeded_repo()
    notifier = ConsoleNotifier()
    # Oversized trade: 1000 shares * $150 = $150k far exceeds 10% single-name cap
    propose = (
        "propose_trade",
        {
            "setup": "long_stock",
            "symbol": "AAPL",
            "side": "BUY",
            "asset_type": "stock",
            "qty": 1000,
            "price": 150.0,
            "currency": "USD",
            "fees": 1.0,
            "rationale": "oversize for testing single-name cap",
        },
    )
    llm = _ScriptedLLM(script=[propose])
    trader = _build_trader(repo, llm, notifier=notifier)

    outcome = trader.run_tick(_context(repo))

    assert outcome.kind == "rejected"
    assert "single-name" in outcome.detail
    assert repo.load_portfolio().positions == ()
    assert repo.trade_count() == 0
    assert notifier.sent == []


def test_get_portfolio_tool_returns_snapshot() -> None:
    repo = _seeded_repo()
    propose = (
        "propose_trade",
        {
            "setup": "long_stock",
            "symbol": "AAPL",
            "side": "BUY",
            "asset_type": "stock",
            "qty": 5,
            "price": 150.0,
            "currency": "USD",
            "fees": 0.0,
            "rationale": "small starter long",
        },
    )
    llm = _ScriptedLLM(
        script=[
            ("get_portfolio", {}),
            ("get_quote", {"symbol": "AAPL"}),
            propose,
        ]
    )
    trader = _build_trader(repo, llm)

    outcome = trader.run_tick(_context(repo))

    assert outcome.kind == "recorded"
    portfolio_tool_record = outcome.llm.tool_calls[0]  # type: ignore[union-attr]
    assert portfolio_tool_record.name == "get_portfolio"
    assert portfolio_tool_record.result["equity_eur"] == "50000.00 EUR"
    assert "progress_to_goal_pct" in portfolio_tool_record.result


def test_option_proposal_flows_through_with_strike_and_expiry() -> None:
    repo = SQLiteDepotRepository()
    repo.save_portfolio(
        Portfolio(
            cash={"EUR": _eur(50_000), "USD": _usd(10_000)},
        )
    )
    propose = (
        "propose_trade",
        {
            "setup": "long_call_or_put",
            "symbol": "AAPL",
            "side": "BUY",
            "asset_type": "option",
            "qty": 1,
            "price": 3.5,
            "currency": "USD",
            "fees": 0.65,
            "expiry": "2026-06-19",
            "strike": 200.0,
            "right": "C",
            "rationale": "delta-30 weekly call after sustained uptrend",
        },
    )
    llm = _ScriptedLLM(script=[("get_option_chain", {"underlying": "AAPL"}), propose])
    notifier = ConsoleNotifier()
    trader = _build_trader(repo, llm, notifier=notifier)

    outcome = trader.run_tick(_context(repo))

    assert outcome.kind == "recorded"
    pos = repo.load_portfolio().positions[0]
    assert pos.asset_type == "option"
    assert pos.expiry == date(2026, 6, 19)
    assert pos.strike == _usd("200.00")
    assert pos.right == "C"
    assert "C @ strike 200.00 USD" in notifier.sent[0].subject


def test_no_tool_call_at_all_results_in_skip() -> None:
    repo = _seeded_repo()
    llm = _ScriptedLLM(script=[])
    trader = _build_trader(repo, llm)

    outcome = trader.run_tick(_context(repo))

    assert outcome.kind == "skipped"
    assert "no proposal" in outcome.detail
