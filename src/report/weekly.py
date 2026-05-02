"""Weekly review: build a Markdown summary from recent snapshots.

Reads-only over the depot, no business decisions, no LLM calls. The
operator-facing weekly review email contains this Markdown body.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from src.depot.money import Money
from src.notify.interfaces import WeeklySummary

_SNAPSHOT_LOOKBACK = 14  # days; comfortably covers a 7-day window


class SnapshotReader(Protocol):
    def recent_snapshots(self, limit: int = 30) -> list[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class WeekRange:
    start: date  # exclusive lower bound
    end: date  # the snapshot date used as week-ending


def _filter_to_week(
    snapshots: Sequence[dict[str, Any]], week_ending: date
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return (latest_in_week, earliest_at_or_before_week_start)."""
    latest: dict[str, Any] | None = None
    earliest_pre: dict[str, Any] | None = None
    week_start = week_ending - timedelta(days=7)

    for snap in snapshots:
        snap_date = _as_date(snap["ts"])
        if snap_date <= week_ending and (
            latest is None or snap_date > _as_date(latest["ts"])
        ):
            latest = snap
        if snap_date <= week_start and (
            earliest_pre is None or snap_date > _as_date(earliest_pre["ts"])
        ):
            earliest_pre = snap
    return latest, earliest_pre


def _as_date(ts: object) -> date:
    if isinstance(ts, datetime):
        return ts.date()
    if isinstance(ts, date):
        return ts
    raise TypeError(f"unsupported ts type: {type(ts).__name__}")


def build_weekly_summary(
    reader: SnapshotReader, *, week_ending: date, open_position_count: int
) -> WeeklySummary:
    snapshots = reader.recent_snapshots(limit=_SNAPSHOT_LOOKBACK)
    latest, baseline = _filter_to_week(snapshots, week_ending)

    if latest is None:
        return WeeklySummary(
            week_ending=week_ending,
            equity_eur=Money.zero("EUR"),
            week_pnl_eur=Money.zero("EUR"),
            week_pnl_pct=0.0,
            open_position_count=open_position_count,
            notes="No snapshot recorded for this week.",
        )

    equity = latest["equity_eur"]
    if baseline is None:
        pnl_eur = Money.zero("EUR")
        pnl_pct = 0.0
        notes = "No baseline snapshot from prior week; reporting zero P&L."
    else:
        pnl_eur = equity - baseline["equity_eur"]
        pnl_pct = (
            float(Decimal(pnl_eur.minor) / Decimal(baseline["equity_eur"].minor) * 100)
            if not baseline["equity_eur"].is_zero()
            else 0.0
        )
        notes = (
            f"### Snapshot points\n"
            f"- Baseline ({_as_date(baseline['ts']).isoformat()}): "
            f"{baseline['equity_eur']}\n"
            f"- Latest ({_as_date(latest['ts']).isoformat()}): {equity}\n"
        )

    return WeeklySummary(
        week_ending=week_ending,
        equity_eur=equity,
        week_pnl_eur=pnl_eur,
        week_pnl_pct=pnl_pct,
        open_position_count=open_position_count,
        notes=notes,
    )
