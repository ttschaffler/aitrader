"""Settings: env substitution, parsing, full load roundtrip."""

from __future__ import annotations

from pathlib import Path

import pytest
from src.config import load_settings, parse_settings, substitute_env


def test_substitute_env_replaces_in_strings() -> None:
    raw = {"smtp": {"host": "${SMTP_HOST}", "port": 587}}
    out = substitute_env(raw, {"SMTP_HOST": "smtp.example.com"})
    assert out["smtp"]["host"] == "smtp.example.com"
    assert out["smtp"]["port"] == 587


def test_substitute_env_empties_missing_vars() -> None:
    out = substitute_env({"k": "${MISSING}"}, {})
    assert out["k"] == ""


def test_substitute_env_recurses_into_lists_and_dicts() -> None:
    raw = {"a": ["${X}", {"b": "${Y}"}]}
    out = substitute_env(raw, {"X": "x", "Y": "y"})
    assert out == {"a": ["x", {"b": "y"}]}


def _full_raw() -> dict[str, object]:
    return {
        "depot": {
            "base_currency": "EUR",
            "starting_cash_eur": 50_000,
            "goal_eur": 100_000,
        },
        "risk": {
            "max_single_name_pct": 0.10,
            "max_total_premium_pct": 0.10,
            "max_per_trade_premium_pct": 0.02,
            "daily_loss_cutoff_pct": -0.03,
            "weekly_loss_cutoff_pct": -0.08,
            "cutoff_minutes_before_close": 30,
        },
        "schedule": {
            "timezone": "Europe/Berlin",
            "us_session_minutes": 20,
            "de_session_minutes": 20,
            "weekly_review_dow": "sunday",
            "weekly_review_time": "19:00",
            "eod_snapshot_time": "22:15",
        },
        "watchlist": {
            "us": ["AAPL", "MSFT"],
            "de": ["SAP.DE", "SIE.DE"],
        },
        "anthropic": {
            "api_key": "key",
            "model_intraday": "claude-sonnet-4-6",
            "model_weekly": "claude-opus-4-7",
            "prompt_cache": True,
        },
        "finnhub": {"api_key": "fkey"},
        "dbg": {
            "api_key": "dkey",
            "eurex_refdata_url": "https://example.com/",
            "cache_dir": "data/cache/dbg",
        },
        "smtp": {
            "host": "smtp.example.com",
            "port": 587,
            "username": "u",
            "password": "p",
            "from_address": "f@e.com",
            "to_address": "t@e.com",
        },
        "logging": {"level": "INFO", "json": True},
    }


def test_parse_settings_full_roundtrip() -> None:
    settings = parse_settings(_full_raw())

    assert settings.depot.starting_cash_eur == 50_000
    assert settings.risk.daily_loss_cutoff_pct == -0.03
    assert settings.watchlist.all_symbols == ("AAPL", "MSFT", "SAP.DE", "SIE.DE")
    assert settings.anthropic.model_intraday == "claude-sonnet-4-6"
    assert settings.smtp.port == 587


def test_parse_settings_missing_section_raises() -> None:
    raw = _full_raw()
    del raw["risk"]
    with pytest.raises(KeyError):
        parse_settings(raw)


def test_load_settings_with_env_substitution(tmp_path: Path) -> None:
    yaml_path = tmp_path / "settings.yaml"
    yaml_path.write_text(
        """
depot:
  base_currency: EUR
  starting_cash_eur: 50000
  goal_eur: 100000
risk:
  max_single_name_pct: 0.10
  max_total_premium_pct: 0.10
  max_per_trade_premium_pct: 0.02
  daily_loss_cutoff_pct: -0.03
  weekly_loss_cutoff_pct: -0.08
  cutoff_minutes_before_close: 30
schedule:
  timezone: Europe/Berlin
  us_session_minutes: 20
  de_session_minutes: 20
  weekly_review_dow: sunday
  weekly_review_time: "19:00"
  eod_snapshot_time: "22:15"
watchlist:
  us: [AAPL]
  de: [SAP.DE]
anthropic:
  api_key: ${ANTHROPIC_KEY}
  model_intraday: claude-sonnet-4-6
  model_weekly: claude-opus-4-7
  prompt_cache: true
finnhub:
  api_key: ${FH_KEY}
dbg:
  api_key: ${DBG_KEY}
  eurex_refdata_url: https://example.com/
  cache_dir: data/cache/dbg
smtp:
  host: ${SMTP_HOST}
  port: 587
  username: u
  password: p
  from_address: f@e.com
  to_address: t@e.com
logging:
  level: INFO
  json: true
""",
        encoding="utf-8",
    )

    env = {
        "ANTHROPIC_KEY": "secret-anthropic",
        "FH_KEY": "secret-fh",
        "DBG_KEY": "secret-dbg",
        "SMTP_HOST": "smtp.somewhere.com",
    }
    settings = load_settings(yaml_path, env)

    assert settings.anthropic.api_key == "secret-anthropic"
    assert settings.smtp.host == "smtp.somewhere.com"
    assert settings.dbg.api_key == "secret-dbg"
