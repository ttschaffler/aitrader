# CLAUDE.md — AI Trading Agent (Virtual Depot)

Instructions for Claude Code when implementing the project described in
[`irtrader_plan.md`](./irtrader_plan.md).

## Project overview
Python 3.11+ application that runs a virtual €50,000 paper-trading depot,
scans US + DE equities and US options every 15–30 min, proposes trades
via a hybrid LLM-within-rule-guardrails strategy, records them in SQLite,
and emails the user. Market data: `yfinance`, Deutsche Börse Group API
Platform (Eurex Reference Data GraphQL), Finnhub, ECB. Reasoning: Claude
API (`claude-sonnet-4-6` intraday, `claude-opus-4-7` for the weekly
review), with prompt caching on the system prompt.

Source of truth for scope and architecture: `irtrader_plan.md`.

---

## Non-negotiable rules

### Virtual depot only
- **Never** implement real order routing, real broker APIs, or anything
  that could send an order to an exchange or broker. All trades live in
  SQLite only.
- **Never** log, commit, or print API keys, SMTP passwords, or Anthropic
  keys. Secrets come from `.env` (git-ignored) loaded into
  `config/settings.yaml` placeholders.

### SOLID principles
Every module and class must visibly honor SOLID. When a change would
break one of these, stop and refactor before continuing.

- **S — Single Responsibility**
  - One reason to change per module/class.
  - `portfolio.py` = accounting only; `risk.py` = rule checks only;
    `trader.py` = orchestration only; adapters = I/O only.
  - No business logic inside data adapters. No I/O inside `portfolio.py`
    beyond the SQLite repository.

- **O — Open/Closed**
  - Adding a new data source (e.g. another DBG API) must not modify
    existing adapters — add a new adapter class implementing the same
    interface.
  - Adding a new strategy setup must not modify existing setups — add a
    new `Setup` subclass and register it.

- **L — Liskov Substitution**
  - All `MarketDataSource` implementations must be drop-in replaceable.
    No subclass may narrow inputs or strengthen exceptions vs. the base
    contract.

- **I — Interface Segregation**
  - Keep interfaces small and role-specific: `QuoteSource`,
    `OptionChainSource`, `NewsSource`, `Notifier`, `TradeRecorder`.
  - Don't force a caller to depend on methods it doesn't use.

- **D — Dependency Inversion**
  - `agent/trader.py` depends on interfaces (`QuoteSource`, `Notifier`,
    `TradeRecorder`, `RiskChecker`), never on concrete classes.
  - Concrete adapters are wired in `main.py` / `scheduler.py` via a
    small composition root. No global singletons inside business logic.

### Testing policy — run after every change
After **every** code change, before moving on, run in this order:

1. `ruff check .` and `ruff format --check .`
2. `mypy src`
3. `pytest -q`
4. If tests or types fail: fix before doing anything else. Do not stack
   further changes on top of a red build.

When adding a feature:
- Write/extend tests in `tests/` **first** or alongside the code.
- Every new class has at least one unit test; every new bug-fix adds a
  regression test that fails before the fix.
- Deterministic tests only: never hit live APIs in `pytest`. Stub
  `QuoteSource`, `NewsSource`, `Notifier`, and the Anthropic client
  with fakes/mocks.
- Integration tests against live services live under `tests/integration/`
  and are gated with a marker (`pytest -m integration`) so they're opt-in.

Coverage target: ≥ 85 % on `src/depot/`, `src/agent/risk.py`, and
`src/agent/trader.py`. Lower is allowed elsewhere but must be explained.

---

## Canonical commands
```bash
# setup
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt

# quality gate (run after every change)
ruff check . && ruff format --check . && mypy src && pytest -q

# seed the virtual depot
python scripts/seed_depot.py

# one manual tick (useful for dev)
python scripts/run_tick.py

# start the scheduler (intraday loop)
python -m src.scheduler

# integration tests (hits live APIs; requires keys)
pytest -m integration
```

---

## Implementation guidance

### Layering (enforced by imports)
```
agent   → depot, data (interfaces), notify (interfaces), risk
risk    → depot (read-only)
depot   → (SQLite only — no external I/O)
data    → (external I/O only — no business logic)
notify  → (external I/O only — no business logic)
report  → depot (read-only)
scheduler, scripts → compose concrete adapters
```
Circular imports or `agent` importing concrete adapters is a bug.

### Money & FX
- All internal accounting in **minor units (cents)** as `int`, not float.
- Single `Money` value object with currency; no raw floats for prices
  once data crosses the adapter boundary.
- FX conversion is a pure function on a daily-cached rate; never inside
  portfolio mutation code.

### Risk rules
- `risk.py` is **pure** — takes a proposed trade + current portfolio,
  returns `Approved | Rejected(reason)`. No side effects, no DB writes,
  no network.
- Every rule from the plan (10 % single-name cap, 2 % premium cap,
  −3 % daily cutoff, −8 % weekly cutoff, session hours, 30 min
  cut-off before close) has its own function and its own test.

### Agent / Claude usage
- System prompt lives in `src/agent/prompt.py` and is marked for
  **prompt caching** (`cache_control: {"type": "ephemeral"}` on the
  final system content block).
- Strategy menu (the 6 setups) is enforced via Claude tool definitions;
  the agent cannot propose anything off-menu.
- `trader.py` never imports `anthropic` directly outside a thin
  `LLMClient` interface — this keeps the tool-use loop swappable/testable.
- Each tick logs: model, input tokens, cached tokens, output tokens,
  latency. Review these regularly.

### Deutsche Börse adapter
- `dbg_adapter.py` exposes a small, typed API (`get_product(...)`,
  `get_instruments(product, expiry)`).
- Reference data is cached daily on disk (e.g. `data/cache/dbg/YYYY-MM-DD.json`).
- Rate-limit aware: on HTTP 429, back off exponentially; never hammer.

### Email notifier
- `Notifier` interface with `send_trade_proposal(trade, portfolio)` and
  `send_daily_summary(summary)`.
- SMTP implementation uses stdlib only; a `ConsoleNotifier` fake is
  used in tests.

### Logging
- `structlog` or stdlib `logging` with JSON formatter.
- **Never** log full LLM prompts at INFO (risk of leaking keys embedded
  in context). Log at DEBUG, gated.

---

## Definition of done (per change)
A change is done only when **all** of these are true:
1. Code compiles, types check (`mypy`), lints clean (`ruff`).
2. All existing tests pass; new tests cover the change.
3. SOLID boundaries still hold (no adapter leaked business logic, no
   business module grew external I/O, no cross-layer imports added).
4. No secret is in the diff.
5. Commit message is descriptive (what + why, not how).
6. For trading-logic changes: a risk-rule test is added or updated.

---

## What NOT to build (out of scope until explicitly asked)
- Real broker integration.
- Eurex options **trading** setups (reference data only for now).
- Streamlit or any GUI.
- A7 / historical backtesting.
- Multi-user, auth, web server.

Keep the surface area small. The MVP is: seed → tick → propose → email.
