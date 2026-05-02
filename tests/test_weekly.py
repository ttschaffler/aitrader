"""Weekly review report builder."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from src.depot.money import Money
from src.report.weekly import build_weekly_summary


def _eur(amount: int | str) -> Money:
    return Money.of(amount, "EUR")


def _snap(ts: datetime, equity: Money) -> dict[str, Any]:
    return {
        "ts": ts,
        "equity_eur": equity,
        "cash_eur": equity,
        "exposure_eur": _eur(0),
        "unrealized_pnl_eur": _eur(0),
    }


class _FakeReader:
    def __init__(self, snapshots: list[dict[str, Any]]) -> None:
        self.snapshots = snapshots

    def recent_snapshots(self, limit: int = 30) -> list[dict[str, Any]]:
        return self.snapshots[:limit]


def test_no_snapshots_returns_zeroed_summary_with_explanation() -> None:
    reader = _FakeReader([])
    summary = build_weekly_summary(
        reader, week_ending=date(2026, 5, 3), open_position_count=0
    )

    assert summary.equity_eur.is_zero()
    assert summary.week_pnl_pct == 0.0
    assert "No snapshot" in summary.notes


def test_no_baseline_uses_zero_pnl_and_notes_baseline_missing() -> None:
    reader = _FakeReader(
        [
            _snap(datetime(2026, 5, 3, 22, 15), _eur(50_000)),
        ]
    )
    summary = build_weekly_summary(
        reader, week_ending=date(2026, 5, 3), open_position_count=0
    )

    assert summary.equity_eur == _eur(50_000)
    assert summary.week_pnl_eur == _eur(0)
    assert "No baseline" in summary.notes


def test_uses_latest_in_week_and_baseline_outside_week() -> None:
    week_ending = date(2026, 5, 3)
    snapshots = [
        # Order is most-recent first to mimic SQL ordering
        _snap(datetime(2026, 5, 3, 22, 15), _eur(52_000)),
        _snap(datetime(2026, 5, 1, 22, 15), _eur(51_000)),
        _snap(datetime(2026, 4, 26, 22, 15), _eur(50_000)),  # baseline (outside week)
        _snap(datetime(2026, 4, 20, 22, 15), _eur(49_000)),
    ]
    summary = build_weekly_summary(
        _FakeReader(snapshots), week_ending=week_ending, open_position_count=2
    )

    assert summary.equity_eur == _eur(52_000)
    assert summary.week_pnl_eur == _eur(2_000)
    assert summary.week_pnl_pct == 4.0
    assert summary.open_position_count == 2
    assert "Baseline" in summary.notes
    assert "2026-04-26" in summary.notes
    assert "2026-05-03" in summary.notes


def test_baseline_falls_on_week_start_boundary() -> None:
    week_ending = date(2026, 5, 3)
    week_start = week_ending - timedelta(days=7)  # 2026-04-26
    snapshots = [
        _snap(datetime(2026, 5, 3, 22, 15), _eur(50_500)),
        _snap(datetime.combine(week_start, datetime.min.time()), _eur(50_000)),
    ]
    summary = build_weekly_summary(
        _FakeReader(snapshots), week_ending=week_ending, open_position_count=0
    )
    assert summary.week_pnl_eur == _eur(500)
