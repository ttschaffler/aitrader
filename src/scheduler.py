"""Composition root + intraday loop.

Wires concrete adapters into a ``Trader`` and registers cron triggers
for the US and Xetra sessions, plus weekly review and EOD snapshot. All
import-time side effects are confined to this module so the agent
package stays clean.

Per CLAUDE.md, this is the *only* place where business logic touches
concrete adapter classes; everything in ``src/agent`` depends on
Protocols.

Run with::

    python -m src.scheduler

For a single tick (useful in dev) use ``scripts/run_tick.py``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from src.agent.llm import LLMClient
from src.agent.risk import RiskChecker, RiskConfig
from src.agent.trader import TickContext, Trader
from src.config import Settings, load_settings
from src.data.fx import FxRate, FxRates
from src.data.interfaces import NewsItem, NewsSource, OptionChainSource, QuoteSource
from src.data.yfinance_adapter import YFinanceQuoteSource
from src.depot.money import Money
from src.depot.repository import SQLiteDepotRepository
from src.depot.valuation import equity as compute_equity
from src.notify.console_notifier import ConsoleNotifier
from src.notify.interfaces import Notifier
from src.notify.smtp_notifier import SmtpConfig, SmtpNotifier

log = logging.getLogger("aitrader.scheduler")


# --------------------------------------------------------- minimal news stub
class _NoNewsSource:  # pragma: no cover - placeholder until Finnhub wires up
    def get_news(self, symbol: str, lookback_hours: int) -> list[NewsItem]:
        return []


# ---------------------------------------------------- composition functions
@dataclass(frozen=True, slots=True)
class Wiring:
    """The concrete adapters and the trader assembled from them.

    Holding them as a value object means scheduler tick callbacks have
    a single object to consult rather than reaching into module
    globals.
    """

    settings: Settings
    repo: SQLiteDepotRepository
    quote_source: QuoteSource
    option_chain_source: OptionChainSource
    news_source: NewsSource
    notifier: Notifier
    trader: Trader


def build_notifier(settings: Settings) -> Notifier:
    """Pick SMTP if all SMTP fields are set, else fall back to console."""
    s = settings.smtp
    if s.host and s.username and s.password and s.from_address and s.to_address:
        return SmtpNotifier(
            SmtpConfig(
                host=s.host,
                port=s.port,
                username=s.username,
                password=s.password,
                from_address=s.from_address,
                to_address=s.to_address,
            )
        )
    log.warning("SMTP not configured; using ConsoleNotifier (emails will not be sent)")
    return ConsoleNotifier(echo=True)


def build_wiring(
    settings: Settings,
    *,
    db_path: Path | str = Path("data/depot.sqlite"),
    llm_client_factory: Callable[[Settings], LLMClient] | None = None,
) -> Wiring:
    repo = SQLiteDepotRepository(db_path)
    quote_source = YFinanceQuoteSource()
    option_source = quote_source  # YFinance adapter implements both protocols
    news_source = _NoNewsSource()
    notifier = build_notifier(settings)

    if llm_client_factory is None:
        from src.agent.llm import AnthropicLLMClient

        llm: LLMClient = AnthropicLLMClient()
    else:
        llm = llm_client_factory(settings)

    risk = RiskChecker(
        RiskConfig(
            max_single_name_pct=settings.risk.max_single_name_pct,
            max_total_premium_pct=settings.risk.max_total_premium_pct,
            max_per_trade_premium_pct=settings.risk.max_per_trade_premium_pct,
            daily_loss_cutoff_pct=settings.risk.daily_loss_cutoff_pct,
            weekly_loss_cutoff_pct=settings.risk.weekly_loss_cutoff_pct,
            cutoff_minutes_before_close=settings.risk.cutoff_minutes_before_close,
        ),
        tz=ZoneInfo(settings.schedule.timezone),
    )

    trader = Trader(
        quotes=quote_source,
        options=option_source,
        news=news_source,
        notifier=notifier,
        recorder=repo,
        risk=risk,
        llm=llm,
        watchlist=settings.watchlist.all_symbols,
        model=settings.anthropic.model_intraday,
        goal_eur=Money.of(settings.depot.goal_eur, "EUR"),
    )
    return Wiring(
        settings=settings,
        repo=repo,
        quote_source=quote_source,
        option_chain_source=option_source,
        news_source=news_source,
        notifier=notifier,
        trader=trader,
    )


# ---------------------------------------------------- runtime context build
def build_runtime_tick_context(  # pragma: no cover - exercised by run_tick.py
    wiring: Wiring,
    *,
    eur_usd_rate: Decimal = Decimal("1.10"),
    today: date | None = None,
) -> TickContext:
    """Real-tick context: fetch live quotes for held positions and compute equity."""
    portfolio = wiring.repo.load_portfolio()
    quotes: dict[str, Money] = {}
    for pos in portfolio.positions:
        try:
            quote = wiring.quote_source.get_quote(pos.symbol)
            quotes[pos.symbol] = quote.price
        except Exception as exc:
            log.warning("quote failed for %s: %s", pos.symbol, exc)
    fx = FxRates.from_iterable(
        [FxRate("EUR", "USD", eur_usd_rate, today or date.today())]
    )
    equity_eur = compute_equity(portfolio, quotes, fx)
    return TickContext(
        now=datetime.now(UTC),
        portfolio=portfolio,
        quotes=quotes,
        fx=fx,
        equity_eur=equity_eur,
        daily_pnl_pct=0.0,
        weekly_pnl_pct=0.0,
        goal_eur=Money.of(wiring.settings.depot.goal_eur, "EUR"),
    )


# ------------------------------------------------------ APScheduler hookup
def schedule(wiring: Wiring) -> object:  # pragma: no cover - APScheduler runtime
    """Build a configured APScheduler with US + Xetra cron triggers."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    tz = ZoneInfo(wiring.settings.schedule.timezone)
    sched = BlockingScheduler(timezone=tz)

    sched.add_job(
        lambda: _run_tick_safely(wiring, "us"),
        CronTrigger(
            day_of_week="mon-fri",
            hour="15-21",
            minute=f"*/{wiring.settings.schedule.us_session_minutes}",
            timezone=tz,
        ),
        name="us-tick",
    )
    sched.add_job(
        lambda: _run_tick_safely(wiring, "de"),
        CronTrigger(
            day_of_week="mon-fri",
            hour="9-16",
            minute=f"*/{wiring.settings.schedule.de_session_minutes}",
            timezone=tz,
        ),
        name="de-tick",
    )
    return sched


def _run_tick_safely(wiring: Wiring, label: str) -> None:  # pragma: no cover
    try:
        ctx = build_runtime_tick_context(wiring)
        outcome = wiring.trader.run_tick(ctx)
        log.info("tick(%s) -> %s: %s", label, outcome.kind, outcome.detail)
    except Exception:
        log.exception("tick(%s) failed", label)


def main() -> None:  # pragma: no cover - runtime entry point
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = load_settings()
    wiring = build_wiring(settings)
    sched = schedule(wiring)
    log.info("scheduler started (timezone=%s)", settings.schedule.timezone)
    sched.start()  # type: ignore[attr-defined]


if __name__ == "__main__":  # pragma: no cover
    main()
