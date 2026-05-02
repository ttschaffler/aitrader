"""Tick-level orchestration: gather context → ask Claude → validate → record.

The trader depends only on Protocols (``QuoteSource``, ``NewsSource``,
``OptionChainSource``, ``Notifier``, ``LLMClient``). Concrete adapters
are wired in ``src/scheduler.py``.

Outcomes for a tick:
- ``Skipped`` — the model called ``skip_tick`` (or no proposal was
  produced).
- ``Recorded`` — the model proposed a trade, risk approved it, the
  Portfolio was updated and persisted, the trade was logged, and the
  email went out.
- ``Rejected`` — the model proposed a trade but risk rejected it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Protocol

from src.agent.llm import LLMClient, LLMResult
from src.agent.prompt import build_system_blocks
from src.agent.risk import (
    Approved,
    Rejected,
    RiskChecker,
    RiskInputs,
)
from src.agent.tools import tool_schemas
from src.data.fx import FxRates
from src.data.interfaces import NewsSource, OptionChainSource, QuoteSource
from src.depot.money import Money
from src.depot.portfolio import AssetType, Portfolio, Side, Trade
from src.depot.repository import SQLiteDepotRepository
from src.depot.valuation import equity as compute_equity
from src.notify.interfaces import Notifier, TradeProposalMessage


@dataclass(frozen=True, slots=True)
class TickContext:
    """Inputs for one tick that the orchestrator computes once and reuses."""

    now: datetime
    portfolio: Portfolio
    quotes: dict[str, Money]
    fx: FxRates
    equity_eur: Money
    daily_pnl_pct: float
    weekly_pnl_pct: float
    goal_eur: Money


@dataclass(frozen=True, slots=True)
class TickOutcome:
    kind: str  # "recorded" | "rejected" | "skipped"
    detail: str
    trade: Trade | None = None
    llm: LLMResult | None = None


# ----------------------------------------------------- tool dispatch
@dataclass
class _DispatchedRecord:
    trade: Trade
    rationale: str


@dataclass
class _SkipDecision:
    reason: str


@dataclass
class _AgentToolHandler:
    """Translates LLM tool calls into adapter calls and captures the
    final ``propose_trade`` / ``skip_tick`` outcome.

    Single responsibility: tool dispatch. Risk checking and persistence
    happen back in the orchestrator after the loop returns.
    """

    quotes: QuoteSource
    options: OptionChainSource
    news: NewsSource
    context: TickContext
    record: _DispatchedRecord | None = field(default=None)
    skip: _SkipDecision | None = field(default=None)

    def handle(self, tool_name: str, tool_input: dict[str, Any]) -> Any:
        if tool_name == "get_quote":
            quote = self.quotes.get_quote(tool_input["symbol"])
            return {
                "symbol": quote.symbol,
                "price": str(quote.price),
                "bid": str(quote.bid) if quote.bid else None,
                "ask": str(quote.ask) if quote.ask else None,
                "volume": quote.volume,
                "as_of": quote.as_of.isoformat(),
            }
        if tool_name == "get_option_chain":
            expiry = (
                date.fromisoformat(tool_input["expiry"])
                if tool_input.get("expiry")
                else None
            )
            chain = self.options.get_option_chain(tool_input["underlying"], expiry)
            return [
                {
                    "expiry": c.expiry.isoformat(),
                    "strike": str(c.strike),
                    "right": c.right,
                    "last": str(c.last) if c.last else None,
                    "bid": str(c.bid) if c.bid else None,
                    "ask": str(c.ask) if c.ask else None,
                    "volume": c.volume,
                    "open_interest": c.open_interest,
                }
                for c in chain
            ]
        if tool_name == "get_news":
            items = self.news.get_news(
                tool_input["symbol"], int(tool_input.get("lookback_hours", 24))
            )
            return [
                {
                    "headline": n.headline,
                    "summary": n.summary,
                    "published_at": n.published_at.isoformat(),
                    "url": n.url,
                }
                for n in items
            ]
        if tool_name == "get_portfolio":
            return _portfolio_snapshot(self.context)
        if tool_name == "propose_trade":
            self.record = _build_record(tool_input)
            return {"status": "received", "next": "awaiting risk check"}
        if tool_name == "skip_tick":
            self.skip = _SkipDecision(reason=tool_input["reason"])
            return {"status": "skipped"}
        raise ValueError(f"unknown tool: {tool_name}")


def _portfolio_snapshot(ctx: TickContext) -> dict[str, Any]:
    return {
        "equity_eur": str(ctx.equity_eur),
        "cash": {c: str(m) for c, m in ctx.portfolio.cash.items()},
        "positions": [
            {
                "symbol": p.symbol,
                "asset_type": p.asset_type,
                "qty": p.qty,
                "avg_price": str(p.avg_price),
                "expiry": p.expiry.isoformat() if p.expiry else None,
                "strike": str(p.strike) if p.strike else None,
                "right": p.right,
            }
            for p in ctx.portfolio.positions
        ],
        "goal_eur": str(ctx.goal_eur),
        "progress_to_goal_pct": _progress_pct(ctx.equity_eur, ctx.goal_eur),
        "daily_pnl_pct": ctx.daily_pnl_pct,
        "weekly_pnl_pct": ctx.weekly_pnl_pct,
    }


def _build_record(tool_input: dict[str, Any]) -> _DispatchedRecord:
    side: Side = "SELL" if tool_input["side"].upper() == "SELL" else "BUY"
    asset_type: AssetType = (
        "option" if tool_input["asset_type"] == "option" else "stock"
    )
    currency = str(tool_input["currency"]).upper()
    price = Money.of(Decimal(str(tool_input["price"])), currency)
    fees_value = tool_input.get("fees", 0)
    fees = Money.of(Decimal(str(fees_value)), currency)
    expiry = (
        date.fromisoformat(tool_input["expiry"]) if tool_input.get("expiry") else None
    )
    strike = (
        Money.of(Decimal(str(tool_input["strike"])), currency)
        if tool_input.get("strike") is not None
        else None
    )
    raw_right = tool_input.get("right")
    right = raw_right if raw_right in ("C", "P") else None
    trade = Trade(
        symbol=tool_input["symbol"],
        asset_type=asset_type,
        side=side,
        qty=int(tool_input["qty"]),
        price=price,
        fees=fees,
        expiry=expiry,
        strike=strike,
        right=right,
    )
    return _DispatchedRecord(trade=trade, rationale=tool_input["rationale"])


def _progress_pct(equity: Money, goal: Money) -> float:
    if goal.is_zero():
        return 0.0
    return float(Decimal(equity.minor) / Decimal(goal.minor) * 100)


# ----------------------------------------------------- portfolio repository
class TradeRecorder(Protocol):
    """Subset of repository surface the trader depends on."""

    def record_trade(
        self,
        trade: Trade,
        *,
        ts: datetime,
        rationale: str | None = None,
        fx_rate: float | None = None,
    ) -> None: ...

    def save_portfolio(self, portfolio: Portfolio) -> None: ...

    def load_portfolio(self) -> Portfolio: ...


# ----------------------------------------------------- the trader
@dataclass
class Trader:
    """Orchestrates one tick. Pure composition over injected interfaces."""

    quotes: QuoteSource
    options: OptionChainSource
    news: NewsSource
    notifier: Notifier
    recorder: TradeRecorder
    risk: RiskChecker
    llm: LLMClient
    watchlist: tuple[str, ...]
    model: str
    goal_eur: Money = field(default_factory=lambda: Money.of(100_000, "EUR"))

    def run_tick(self, context: TickContext) -> TickOutcome:
        handler = _AgentToolHandler(
            quotes=self.quotes,
            options=self.options,
            news=self.news,
            context=context,
        )
        user_message = _build_user_message(context, self.watchlist)
        result = self.llm.run_tool_use_loop(
            model=self.model,
            system_blocks=build_system_blocks(self.watchlist),
            tools=tool_schemas(),
            initial_user_message=user_message,
            tool_handler=handler,
        )

        if handler.skip is not None and handler.record is None:
            return TickOutcome("skipped", handler.skip.reason, llm=result)
        if handler.record is None:
            return TickOutcome(
                "skipped", "model emitted no proposal or skip", llm=result
            )

        return self._validate_and_record(handler.record, context, result)

    def _validate_and_record(
        self,
        record: _DispatchedRecord,
        context: TickContext,
        llm_result: LLMResult,
    ) -> TickOutcome:
        risk_inputs = RiskInputs(
            trade=record.trade,
            portfolio=context.portfolio,
            quotes=context.quotes,
            fx=context.fx,
            equity_eur=context.equity_eur,
            daily_pnl_pct=context.daily_pnl_pct,
            weekly_pnl_pct=context.weekly_pnl_pct,
            now=context.now,
        )
        risk_result = self.risk.check(risk_inputs)
        if isinstance(risk_result, Rejected):
            return TickOutcome(
                "rejected", risk_result.reason, trade=record.trade, llm=llm_result
            )
        assert isinstance(risk_result, Approved)

        new_portfolio = context.portfolio.apply(record.trade)
        self.recorder.record_trade(
            record.trade, ts=context.now, rationale=record.rationale
        )
        self.recorder.save_portfolio(new_portfolio)

        # Re-compute equity post-trade for the email.
        post_equity = compute_equity(new_portfolio, context.quotes, context.fx)
        cash_eur = (
            context.fx.convert(new_portfolio.cash_in("EUR"), "EUR")
            if "EUR" in new_portfolio.cash
            else Money.zero("EUR")
        )

        self.notifier.send_trade_proposal(
            TradeProposalMessage(
                trade=record.trade,
                rationale=record.rationale,
                equity_eur=post_equity,
                cash_eur=cash_eur,
                progress_to_goal_pct=_progress_pct(post_equity, self.goal_eur),
                proposed_at=context.now,
            )
        )
        return TickOutcome(
            "recorded",
            "trade approved and recorded",
            trade=record.trade,
            llm=llm_result,
        )


def _build_user_message(context: TickContext, watchlist: Iterable[str]) -> str:
    progress = _progress_pct(context.equity_eur, Money.of(100_000, "EUR"))
    lines = [
        f"It is {context.now.isoformat()}.",
        "",
        "## Current depot",
        f"- Equity (EUR): {context.equity_eur}",
        "- Cash buckets: "
        + ", ".join(f"{c}={m}" for c, m in context.portfolio.cash.items()),
        f"- Open positions: {len(context.portfolio.positions)}",
        f"- Daily P&L: {context.daily_pnl_pct * 100:+.2f}%",
        f"- Weekly P&L: {context.weekly_pnl_pct * 100:+.2f}%",
        f"- Progress to EUR 100k goal: {progress:.2f}%",
        "",
        "## Watchlist this tick",
        ", ".join(watchlist),
        "",
        "Decide: propose ONE trade from the strategy menu, or skip the tick. "
        "Use the available tools to gather only the data you actually need.",
    ]
    return "\n".join(lines)


# Helper to bootstrap a TickContext from a repo + market snapshot.
def build_tick_context(
    *,
    repo: SQLiteDepotRepository,
    quotes_for_positions: dict[str, Money],
    fx: FxRates,
    now: datetime | None = None,
    daily_pnl_pct: float = 0.0,
    weekly_pnl_pct: float = 0.0,
    goal_eur: Money | None = None,
) -> TickContext:
    goal = goal_eur or Money.of(100_000, "EUR")
    portfolio = repo.load_portfolio()
    equity_eur = compute_equity(portfolio, quotes_for_positions, fx)
    return TickContext(
        now=now or datetime.now(UTC),
        portfolio=portfolio,
        quotes=quotes_for_positions,
        fx=fx,
        equity_eur=equity_eur,
        daily_pnl_pct=daily_pnl_pct,
        weekly_pnl_pct=weekly_pnl_pct,
        goal_eur=goal,
    )
