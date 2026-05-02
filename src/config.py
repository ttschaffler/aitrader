"""Settings loader: parse ``config/settings.yaml`` with ${ENV} placeholders.

The pure parsing functions (``substitute_env`` and ``parse_settings``)
have no I/O so they're trivial to unit-test. ``load_settings`` is the
thin wrapper that touches the filesystem and ``os.environ``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_PLACEHOLDER = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


@dataclass(frozen=True, slots=True)
class DepotSettings:
    base_currency: str
    starting_cash_eur: int
    goal_eur: int


@dataclass(frozen=True, slots=True)
class RiskSettings:
    max_single_name_pct: float
    max_total_premium_pct: float
    max_per_trade_premium_pct: float
    daily_loss_cutoff_pct: float
    weekly_loss_cutoff_pct: float
    cutoff_minutes_before_close: int


@dataclass(frozen=True, slots=True)
class ScheduleSettings:
    timezone: str
    us_session_minutes: int
    de_session_minutes: int
    weekly_review_dow: str
    weekly_review_time: str
    eod_snapshot_time: str


@dataclass(frozen=True, slots=True)
class WatchlistSettings:
    us: tuple[str, ...]
    de: tuple[str, ...]

    @property
    def all_symbols(self) -> tuple[str, ...]:
        return tuple([*self.us, *self.de])


@dataclass(frozen=True, slots=True)
class AnthropicSettings:
    api_key: str
    model_intraday: str
    model_weekly: str
    prompt_cache: bool


@dataclass(frozen=True, slots=True)
class FinnhubSettings:
    api_key: str


@dataclass(frozen=True, slots=True)
class DBGSettings:
    api_key: str
    eurex_refdata_url: str
    cache_dir: str


@dataclass(frozen=True, slots=True)
class SmtpSettings:
    host: str
    port: int
    username: str
    password: str
    from_address: str
    to_address: str


@dataclass(frozen=True, slots=True)
class LoggingSettings:
    level: str
    json: bool


@dataclass(frozen=True, slots=True)
class Settings:
    depot: DepotSettings
    risk: RiskSettings
    schedule: ScheduleSettings
    watchlist: WatchlistSettings
    anthropic: AnthropicSettings
    finnhub: FinnhubSettings
    dbg: DBGSettings
    smtp: SmtpSettings
    logging: LoggingSettings


# ---------------------------------------------------------------------- pure
def substitute_env(value: Any, env: Mapping[str, str]) -> Any:
    """Recursively replace ``${VAR}`` placeholders in strings."""
    if isinstance(value, str):
        return _PLACEHOLDER.sub(lambda m: env.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: substitute_env(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute_env(v, env) for v in value]
    return value


def parse_settings(raw: dict[str, Any]) -> Settings:
    return Settings(
        depot=DepotSettings(**raw["depot"]),
        risk=RiskSettings(**raw["risk"]),
        schedule=ScheduleSettings(**raw["schedule"]),
        watchlist=WatchlistSettings(
            us=tuple(raw["watchlist"]["us"]),
            de=tuple(raw["watchlist"]["de"]),
        ),
        anthropic=AnthropicSettings(**raw["anthropic"]),
        finnhub=FinnhubSettings(**raw["finnhub"]),
        dbg=DBGSettings(**raw["dbg"]),
        smtp=_smtp_from_raw(raw["smtp"]),
        logging=LoggingSettings(**raw["logging"]),
    )


def _smtp_from_raw(raw: dict[str, Any]) -> SmtpSettings:
    return SmtpSettings(
        host=raw["host"],
        port=int(raw["port"]) if raw["port"] != "" else 0,
        username=raw["username"],
        password=raw["password"],
        from_address=raw["from_address"],
        to_address=raw["to_address"],
    )


# --------------------------------------------------------------------- impure
def load_settings(
    path: Path | str = Path("config/settings.yaml"),
    env: Mapping[str, str] | None = None,
) -> Settings:
    """Read YAML, substitute env, parse."""
    text = Path(path).read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ValueError(f"settings.yaml must be a mapping, got {type(raw).__name__}")
    raw = substitute_env(raw, env if env is not None else os.environ)
    return parse_settings(raw)
