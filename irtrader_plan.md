# AI Trading Agent — Virtual Depot (Paper Trading)

## Context
You want an AI agent that manages a virtual €50,000 portfolio with the goal of
doubling it by trading **US and German stocks plus US options**. The agent must:
- Operate on a **virtual depot only** (no bank/broker integration, no real orders)
- Pull market data and quotes from **free public internet sources**
- **Email you** about any trades it proposes/records in the virtual depot
- Track positions, cash, P&L, and progress toward the €100k goal

Repo is empty — this is a greenfield setup.

## Your chosen configuration
| Decision | Choice |
|---|---|
| Notifier | **Email (SMTP)** |
| Market focus | **US stocks + US options + DE (Xetra) stocks** |
| Strategy style | **Hybrid — LLM within rule guardrails** |
| Scan cadence | **Intraday every 15–30 min** |

## Risk framing
Doubling €50k → €100k is **+100%**. At index returns (~8–10%/yr) this is
~7–9 years; faster means leverage via options, which increases drawdown risk.
Virtual depot is the right place to validate the strategy before real capital.

---

## Architecture

```
 ┌──────────────────────┐   ┌──────────────────────┐
 │  Market Data         │   │  News / Events       │
 │  - yfinance (US, DE) │   │  - Finnhub news      │
 │  - US option chains  │   │  - Earnings cal.     │
 │  - ECB EUR/USD FX    │   │                      │
 └──────────┬───────────┘   └──────────┬───────────┘
            │                          │
            ▼                          ▼
     ┌───────────────────────────────────────────┐
     │  Agent Core (Claude, tool use)            │
     │  - Hybrid: LLM picks from a menu of       │
     │    pre-approved setups, within hard       │
     │    risk rules                             │
     │  - Logs rationale                         │
     └──────────────────┬────────────────────────┘
                        │
     ┌──────────────────┼─────────────────────┐
     ▼                  ▼                     ▼
 ┌─────────┐     ┌─────────────┐       ┌─────────────┐
 │ Virtual │     │ Email       │       │ Reporter    │
 │ Depot   │     │ Notifier    │       │ (daily P&L, │
 │ SQLite  │     │ (SMTP)      │       │ equity crv) │
 └─────────┘     └─────────────┘       └─────────────┘
           ▲
           │
   APScheduler (every 15–30 min during
   US + Xetra trading hours)
```

---

## Components

### 1. Language & runtime
- **Python 3.11+**, managed with `uv` or `pip` + `requirements.txt`
- Single-process app; APScheduler for intraday ticks

### 2. Market data (free)
| Source | Use | Library |
|---|---|---|
| Yahoo Finance | US & DE stocks (e.g. `AAPL`, `SAP.DE`), US options chains, history | `yfinance` |
| **Deutsche Börse Group API Platform** | Authoritative DE/Eurex reference & (selected) market data — see below | `httpx` + GraphQL client (`gql`) |
| Finnhub (free key) | News + earnings calendar | `finnhub-python` |
| ECB | EUR/USD FX daily reference | direct HTTP (XML) |
| Stooq | Backup DE history | `pandas-datareader` |

Currency handling: depot is EUR; US positions are marked to EUR using live
EUR/USD from yfinance (`EURUSD=X`) with ECB as sanity check.

#### 2a. Deutsche Börse Group API Platform
Portal: <https://console.developer.deutsche-boerse.com/apis>
Docs:   <https://docs.developer.deutsche-boerse.com/>

Concrete endpoints we can use:
- **Eurex T7 Reference Data (GraphQL)** — free, public, optionally keyed.
  Base URL: `https://api.developer.deutsche-boerse.com/prod/accesstot7-referencedata/1.1.0/`
  Provides product & instrument reference for **Eurex** (e.g. DAX futures
  `FDAX`, DAX/Euro STOXX options, expiries, strike ladders, contract specs,
  tick sizes, trading hours). Anonymous shared key is rate-limited — create
  a **dedicated app + API key** in the portal for better throughput.
- **Xetra / Eurex reference & market-data products** — discoverable in the
  portal catalog after registration. Some are free/sandbox, others are paid
  subscriptions (e.g. Xetra Core real-time L1/L2). The agent should treat
  paid-tier endpoints as opt-in via `settings.yaml`.
- **A7 analytics platform** (<https://github.com/Deutsche-Boerse/a7>) —
  cloud-based historical & intraday order-by-order data for Xetra, Eurex,
  EEX. Subscription-based; useful later for backtesting / weekly review,
  not required for MVP.

How it plugs into the agent:
- New adapter `src/data/dbg_adapter.py` wraps the platform with one class
  per API (starting with `EurexReferenceDataClient` over GraphQL).
- Reference data is **cached daily** (expiries and strike ladders don't
  change intraday) to stay well within rate limits.
- Enables a future **DAX/Euro STOXX options** setup in the strategy menu,
  replacing the "US options only" limitation once live data is wired in.
- Quotes/last-traded still come from yfinance for MVP; DBG endpoints are
  added incrementally as you unlock them in the portal.

Auth model:
- Register app at the developer portal → receive API key(s).
- Keys stored in `settings.yaml` under `dbg:` (never committed; use
  `.env` + git-ignore).
- Adapter sends the key as an `X-Api-Key` header (or `Authorization`
  where the specific API requires it, per its page in the portal).

### 3. Virtual depot (SQLite, file-based)
Tables:
- `positions` (symbol, qty, avg_price_native, currency, asset_type,
   expiry, strike, right)
- `cash` (currency, balance) — EUR primary, USD sub-account for US trades
- `trades` (ts, symbol, side, qty, price, fees, fx_rate, rationale)
- `snapshots` (ts, equity_eur, cash_eur, exposure_eur, unrealized_pnl)
- `watchlist` (symbol, notes) — curated universe the agent monitors

Seed script creates **€50,000 cash**, empty positions, and a starter
watchlist (e.g., large-cap US + DAX 40 names).

### 4. Agent core — Hybrid LLM + rules

**Claude API (`anthropic` SDK)** drives decisions. Model choice:
- `claude-sonnet-4-6` for each 15–30 min tick (cost/latency)
- `claude-opus-4-7` for weekly strategy review (Sunday)
- **Prompt caching** on the system prompt (strategy rules, risk limits,
  watchlist) — massive cost savings at 15–30 min cadence

**Hybrid model**: LLM chooses from a fixed menu of setups, never free-form:
1. **Long stock** (US or DE) — up to 10% of equity per name
2. **Close stock position** (full or partial)
3. **Long call / long put** (US only) — premium ≤ 2% of equity
4. **Covered call** on an existing long stock position
5. **Cash-secured put** — reserved cash must cover full assignment
6. **Hold / no action**

Naked shorts, spreads beyond the menu, and un-hedged short options are **not
available** to the agent.

**Tools exposed to Claude:**
- `get_quote(symbol)` — latest price, bid/ask, volume
- `get_option_chain(symbol, expiry?)` — US only
- `get_news(symbol, lookback_h)` — Finnhub
- `get_portfolio()` — positions + cash in EUR
- `propose_trade(setup, symbol, qty_or_premium, expiry?, strike?, right?, rationale)`
- `skip_tick(reason)`

### 5. Risk guardrails (hardcoded, pre-LLM)
Every `propose_trade` passes through `risk.py` before it's recorded:
- Max single-name exposure: **10% of equity**
- Max total options premium outstanding: **10% of equity**
- Per-trade options premium: **≤ 2% of equity**
- Daily realized + unrealized loss cutoff: **−3%** → agent halts for the day
- Weekly drawdown cutoff: **−8%** → agent halts, emails review request
- No trading outside exchange hours for the underlying
- No new trades with < 30 min to close

### 6. Scheduling
- **APScheduler** with two cron triggers:
  - US session: every 20 min, 15:30–22:00 Europe/Berlin, Mon–Fri
  - DE/Xetra session: every 20 min, 09:00–17:30 Europe/Berlin, Mon–Fri
- Weekly review job: Sunday 19:00 Europe/Berlin (uses Opus)
- Daily EOD snapshot: 22:15 Europe/Berlin

### 7. Email notifier (SMTP)
- Library: `smtplib` + `email.message` (stdlib); no extra deps
- Config: SMTP host, port, username, app password, from/to addresses
- Two email types:
  1. **Trade proposal email** — per recorded virtual trade: setup, symbol,
     size, price, rationale, new portfolio equity, % to goal
  2. **Daily summary** — equity curve line, today's trades, biggest movers,
     risk-rule status
- Plaintext first; HTML template upgrade later

### 8. Reporting
- Daily equity snapshot → `snapshots` table + appended CSV
- Weekly Markdown report emailed Sunday night
- (Optional later) Streamlit dashboard for local viewing

---

## Required accounts / keys (all free)
- **Anthropic API key** — agent reasoning
- **SMTP credentials** (e.g., Gmail + app password, or a transactional
  provider) + recipient email
- **Finnhub free API key** — news & earnings
- **Deutsche Börse developer portal account** + app → API key for the
  Eurex Reference Data GraphQL endpoint and any additional DBG APIs you
  subscribe to from the catalog
- No broker account required

---

## Repo layout & critical files to create
```
aitrader/
├── config/
│   └── settings.yaml           # keys, thresholds, SMTP, watchlist
├── src/
│   ├── data/
│   │   ├── yfinance_adapter.py # quotes, option chains, history
│   │   ├── dbg_adapter.py      # Deutsche Börse API Platform (Eurex
│   │   │                       # reference data GraphQL; extend with
│   │   │                       # further DBG APIs as subscribed)
│   │   ├── finnhub_adapter.py  # news, earnings
│   │   └── fx.py               # EUR/USD conversion
│   ├── depot/
│   │   ├── schema.sql
│   │   ├── portfolio.py        # positions, cash, mark-to-market
│   │   └── trades.py           # record/validate trades
│   ├── agent/
│   │   ├── trader.py           # Claude tool-use loop
│   │   ├── prompt.py           # cached system prompt w/ rules + menu
│   │   └── risk.py             # hardcoded guardrails
│   ├── notify/
│   │   └── email_smtp.py       # trade + daily summary emails
│   ├── report/
│   │   ├── snapshot.py         # EOD equity snapshot
│   │   └── weekly.py           # Sunday review + email
│   └── scheduler.py            # APScheduler entrypoints
├── scripts/
│   ├── seed_depot.py           # €50k cash init
│   └── run_tick.py             # manual single tick for testing
├── tests/
│   ├── test_portfolio.py
│   ├── test_risk.py
│   └── test_fx.py
├── data/
│   └── depot.sqlite            # created at first run
└── requirements.txt
```

---

## MVP build order
1. `requirements.txt`, repo skeleton, `settings.yaml` template
2. `depot/schema.sql` + `portfolio.py` + `scripts/seed_depot.py` → verify
   €50k seed and simple buy/sell math in tests
3. `data/yfinance_adapter.py` + `fx.py` → live US & DE quote fetch + EUR mark
4. `data/dbg_adapter.py` → register DBG developer app, store API key, wire
   up Eurex Reference Data GraphQL client; daily-cached lookup of DAX
   product & instrument metadata (expiries, strikes)
5. `notify/email_smtp.py` → send a test email end-to-end
6. `agent/risk.py` + `agent/prompt.py` (cached) + `agent/trader.py` with the
   6-setup menu + tool use
7. `scheduler.py` with US + DE intraday triggers
8. `report/snapshot.py` (EOD) + `report/weekly.py` (Sunday)
9. Dry-run for 1 week, review emails & equity curve

---

## Verification plan
1. **Unit tests**:
   - Portfolio math: buy/sell updates qty, avg price, cash (in both EUR & USD)
   - Mark-to-market with FX conversion
   - Risk rules reject oversized positions, premium caps, loss cutoffs
2. **Integration**:
   - Seed depot → run one tick against live yfinance for `AAPL` + `SAP.DE` →
     confirm a proposal is generated, passes risk, recorded in SQLite, and
     a correctly-formatted email lands in the inbox
3. **Scenario**:
   - Inject a synthetic −4% intraday drop → confirm daily-loss cutoff halts
     further proposals and emails a halt notice
4. **Dry-run week**:
   - Run live for 5 trading days; check intraday emails, EOD snapshot, and
     Sunday weekly review
5. **Goal-tracking sanity**:
   - Equity curve in the daily email shows % progress to €100k

---

## Out of scope for MVP (future)
- Real broker integration
- Eurex options (DAX / Euro STOXX 50) **trading** setups — MVP wires the
  Eurex Reference Data API so expiries and strikes are available, but
  live option **quotes** require additional DBG subscriptions or a paid
  feed; add a setup once keyed in
- A7 historical data for backtesting / weekly analytics
- Streamlit dashboard
- Multi-strategy portfolios (momentum vs. mean-reversion sleeves)
- Backtesting harness (useful next step before going live with real money)
