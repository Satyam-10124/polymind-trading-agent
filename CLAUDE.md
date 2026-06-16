# CLAUDE.md

Guidance for working in this repository.

## What this is

**PolyMind** is an autonomous Polymarket trading agent. It watches top whales,
and when several independently agree on the same market, it convenes a 9-agent
"investment committee" (LLM calls via the Virtuals API) that scores the trade
across multiple risk dimensions before sizing and (paper- or live-) executing it.
A React dashboard and a Telegram bot expose live state. The system learns from
every closed trade via a post-mortem loop that feeds lessons back into the prompts.

**Paper mode is the default and is safe.** `PAPER_MODE=true` (env) means no real
orders are placed — `executor/clob_client.py` short-circuits to mock fills.

## Layout

```
backend/
  main.py              APScheduler entrypoint; wires jobs + Telegram polling
  api.py               FastAPI read API for the dashboard
  config.py            All env-driven config constants
  db/models.py         SQLite schema, migrations, and ALL persistence helpers
  whale/
    monitor.py         Leaderboard fetch, fresh-trade scan, CONSENSUS engine
    profiler.py        Per-wallet behavioral profiles (category win rates, etc.)
  brain/
    committee.py       9-agent pipeline + deterministic portfolio hard-checks
    prompts.py         System/user prompt templates + tool schemas
    claude_agent.py    Legacy single-pass analyst + daily report (still used)
  risk/
    kelly.py           Enhanced dynamic-fraction Kelly + drawdown breaker
    tp_sl_manager.py   Take-profit / stop-loss / time-stop checks
  executor/clob_client.py   Order placement (mock in paper mode)
  bot/telegram_bot.py  Commands + alerts
  scheduler/jobs.py    The orchestration glue (scan → committee → execute → learn)
dashboard/src/
  App.tsx              Sidebar nav + page router (plain useState, no router lib)
  hooks/useApi.ts      Polling fetch hooks (all reads go through /api)
  pages/               Dashboard, Positions, Signals, Committee, Whales, Lessons
  components/StatCard.tsx
```

## The committee pipeline (the heart of the system)

Entry: `scheduler/jobs.py::whale_scan_job` (runs every `SCAN_INTERVAL_SECONDS`).

1. **Leaderboard → whales** — `monitor.get_leaderboard` + `filter_whales`.
2. **Fresh trades** — `monitor.scan_new_whale_trades`; each new whale bet is
   recorded into a rolling buffer via `monitor.record_bet`.
3. **Consensus gate** — `monitor.compute_consensus(market_id, direction)`. The
   committee only convenes if `CONSENSUS_MIN_WHALES` (default 3) tracked whales
   bet the same direction on the same market within `CONSENSUS_WINDOW_HOURS`.
   `consensus_score` ∈ [0,1] blends whale count, tier weights (by PnL), and recency.
4. **Committee** — `brain/committee.py::run_committee` runs, in order:
   1. Whale Intent (uses profiler's category win rates + conviction style)
   2. Market Efficiency
   3. Event Archetype
   4. **CRO Red Team** — attacks liquidity / event-timing / whale-exit /
      correlation; outputs `rejection_risk_pct` + top 3 failure modes.
      `>40%` → hard veto.
   5. **Portfolio** — `portfolio_hard_checks()` (deterministic) runs *before* the
      LLM agent: rejects >3 same-day resolutions, rejects >60% YES concentration,
      collapses correlated markets (shared `event_key`) to one position. Then the
      LLM portfolio agent runs.
   6. Sizing (LLM) → `capital_allocation`, scaled by consensus.
   7. Final committee vote → verdict.
5. **Sizing** — `risk/kelly.py::kelly_bet` recomputes size with a dynamic Kelly
   fraction (from the last 20 outcomes) and a drawdown circuit breaker, logging the
   full breakdown to `sizing_decisions`. Final bet = `min(committee_alloc, kelly)`.
6. **Execute + persist** — `place_order`, `save_position`, `save_committee_report`,
   `save_signal`.
7. **Learn** — `post_mortem_job` (every 30 min) runs a post-mortem on each closed
   trade, explodes it into `lessons_learned`, and `mark_lessons_applied` records
   whether prior same-category lessons reduced losses. `run_committee` injects the
   last 5 same-category lessons into the final committee prompt.

## Data model (SQLite, `backend/polymind.db`)

`positions`, `signals`, `stats`, `post_mortems`, `committee_reports`,
`whale_profiles`, `lessons_learned`, `sizing_decisions`, `consensus_events`.

Schema lives entirely in `db/models.py::init_db`. **New columns must go through
`_run_migrations()` / `_safe_add_column`** — never assume a fresh DB, existing
deployments are migrated in place on startup.

## Conventions

- **All persistence goes through `db/models.py`.** Don't open `sqlite3`
  connections elsewhere; add a helper function instead. Helpers open and close
  their own connection per call (no shared/global connection).
- **Config via `config.py` only**, read from env with sane defaults. Add new
  tunables there and mirror them in `backend/.env.example`.
- **LLM agents** return structured data via tool schemas (`*_TOOL` dicts in
  `committee.py`). Each agent has a fallback dict so a failed/empty API call never
  crashes the pipeline — preserve this pattern when adding agents.
- **Dashboard reads only.** Every page polls `/api/*` through a hook in
  `useApi.ts`; there are no mutations from the UI. Dark theme palette: bg
  `#060C18`/`#0D1526`, borders `#1A2740`, accent `#3BD6AC`, muted text `#6B7FA3`.
- Money is USDC; prices are 0–1 probabilities (×100 for ¢ display).
- Run `python3` (not `python`) in this environment.

## Gotchas

- **Consensus buffer is in-memory** (`monitor._recent_bets`). It resets on
  restart, so consensus needs whales to bet within one running window. Profiles
  (`profiler._profiles`) are likewise cached in-process but also persisted.
- **`run_committee` will hard-reject before reaching sizing** on a CRO veto
  (>40%), a portfolio hard-check failure, or an LLM portfolio "Reject". The
  returned dict still includes whatever `committee_reports` were produced so far.
- **CRO field aliases**: the tool now emits `rejection_risk_pct` /
  `top_failure_modes`, but `run_cro` also sets legacy `rejection_probability` /
  `fatal_flaws` for backward compatibility — read whichever, both are present.
- **`derive_event_key` is a heuristic** (sorted salient tokens). It can
  false-positive/negative on correlation grouping; it is intentionally cheap and
  conservative, not a semantic matcher.
- **Whale category win rates depend on the data API returning per-trade `pnl`**;
  when absent, per-category rates simply stay empty — handle missing keys.
- Telegram/CLOB libs are optional imports — code must degrade gracefully when
  `_bot` is `None` or `py-clob-client` is missing (it prints/mocks instead).
- `claude_agent.py` and the legacy `*_COPY_*` / `MARKET_SCAN_*` prompts are kept
  for the daily report and fallback single-pass mode; the committee is the
  primary path.

## Quick commands

```bash
# Syntax-check all backend files
cd backend && find . -name '*.py' -not -path '*/__pycache__/*' -exec python3 -m py_compile {} +

# Run the agent (paper mode)
cd backend && python3 main.py

# Run the API
cd backend && uvicorn api:app --port 8000

# Dashboard
cd dashboard && npm install && npm run dev   # typecheck: npx tsc --noEmit
```
