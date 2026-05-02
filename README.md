# aitrader

Virtual EUR 50,000 paper-trading depot driven by Claude. Scans US + DE
equities and US options every 15-30 minutes during exchange hours,
proposes trades through a hybrid LLM-within-rule-guardrails strategy,
records every (virtual) fill in SQLite, and emails the operator. No real
broker is touched.

See [`irtrader_plan.md`](./irtrader_plan.md) for the full architecture
and [`CLAUDE.md`](./CLAUDE.md) for the rules every code change must
follow.

## Status

MVP code complete (steps 1-8). Next operational step is the dry-run
(step 9 in the plan) - documented below.

## Setup

```bash
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt

cp .env.example .env                              # fill in real keys
cp config/settings.yaml.example config/settings.yaml

python scripts/seed_depot.py                      # create EUR 50k depot
```

Required keys in `.env`:

- `ANTHROPIC_API_KEY` - the Claude API
- `FINNHUB_API_KEY` - news + earnings (free tier)
- `DBG_API_KEY` - Deutsche Boerse developer portal (Eurex reference data)
- `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` /
  `SMTP_FROM` / `SMTP_TO` - email delivery (Gmail app password works)

If SMTP fields are blank, the agent falls back to the
`ConsoleNotifier` and prints emails to stdout (useful for first
runs).

## Usage

```bash
# quality gate (run after every code change)
ruff check . && ruff format --check . && mypy src && pytest -q

# one manual tick (smoke test before scheduling)
python scripts/run_tick.py

# start the intraday scheduler (US + Xetra cron triggers)
python -m src.scheduler

# integration tests (live APIs; opt-in)
pytest -m integration
```

## Dry-run procedure (step 9 of the plan)

The MVP must run live for one trading week before any real-money
decisions are even considered.

1. **Pre-flight (Friday evening)**
   - All quality gate checks pass on the deploy host.
   - `python scripts/seed_depot.py` produced a fresh `data/depot.sqlite`
     with EUR 50,000 cash and the default watchlist.
   - One manual `python scripts/run_tick.py` succeeds end-to-end:
     a tick is logged, no proposal/risk error, an email or console
     output appears.

2. **Run (Mon-Fri)**
   - `python -m src.scheduler` started under a process supervisor
     (`systemd`, `supervisord`, or simply `tmux` for a first dry-run).
   - APScheduler fires US and Xetra ticks every 20 minutes within
     trading hours; the EOD snapshot job records equity nightly.

3. **Daily review checklist**
   - Inbox: each tick that produced a recorded trade should have a
     proposal email; daily summary arrives once after EOD.
   - SQLite: `data/depot.sqlite` `trades` table grew, `snapshots`
     gained one row.
   - Logs: zero `tick(...) failed` entries, zero
     `quote failed for ...` warnings on watchlist symbols.
   - Risk: at least one rejected proposal somewhere in the week is
     evidence the guardrails are working; zero rejections after a
     full week is suspicious.

4. **Sunday weekly review**
   - The weekly review job (Opus model) emails the Markdown summary.
   - Compare the equity curve against a simple buy-and-hold of the
     watchlist over the same week.

5. **Decision gate**
   - Only after a clean dry-run week (no fatal errors, plausible
     trades, risk rules fired at least once) is the project a candidate
     for any further phase.

## Repository layout

```
src/
  agent/    # trader, risk, prompt, llm, tools (depend on interfaces only)
  data/     # yfinance, dbg, fx adapters + interfaces
  depot/    # SQLite repo, Money, Portfolio, valuation, seed
  notify/   # Notifier interface, SMTP delivery, ConsoleNotifier fake
  report/   # EOD snapshot + weekly review
  config.py # settings.yaml loader with .env substitution
  scheduler.py # composition root + APScheduler hookup
scripts/    # seed_depot.py, run_tick.py
tests/      # 134 deterministic tests; tests/integration/ are opt-in
```

## Out of scope (deliberately)

- Real broker integration.
- Eurex options *trading* setups (reference data only for now).
- Streamlit dashboard.
- Backtesting (A7 historical data).
- Multi-user, auth, web server.
