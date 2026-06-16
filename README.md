# PolyMind — Institutional Prediction Market Trading Agent

> **Not a copy-trading bot. An autonomous investment committee.**

PolyMind watches Polymarket's top whale wallets, then routes every potential trade through a 9-agent AI committee — powered by Claude Opus via [Virtuals Compute](https://virtuals.io) — before a single dollar is committed. The result is a system that thinks more like a Goldman Sachs PM than a script.

---

## Why PolyMind Is Different

Most Polymarket bots do this:

```
Whale bets YES → bot bets YES → lose money when whale was wrong
```

PolyMind does this:

```
Whale bets YES
    ↓
[Whale Intent Engine]     "Is this real alpha or just market making?"
    ↓
[Market Efficiency Auditor] "Is the edge already priced in?"
    ↓
[Event Archetype Engine]  "Central Bank event — overreaction likely"
    ↓
[Adversarial CRO]         "Destroy the thesis. Find every reason to reject."
    ↓ (hard veto if rejection risk > 40%)
[Portfolio Risk Engine]   "Does this increase fragility?"
    ↓
[Confidence-Adjusted Kelly] "Size for survival, not maximum return"
    ↓
[Investment Committee]    APPROVE / WATCH / REJECT
    ↓ (30 min after close)
[Post-Trade Learning]     "Edge was phantom. Don't repeat this mistake."
```

The CRO alone vetoes more than half of all trades. That's the point. The only trades that get through are ones where 6 independent expert perspectives simultaneously agree the opportunity is real.

---

## The 9-Agent Committee

| # | Agent | Role | Veto Power |
|---|-------|------|-----------|
| 1 | **Investment Committee** | Final verdict (Goldman/Citadel/RenTech panel) | Final vote |
| 2 | **Whale Intent Engine** | Forensic motive analysis — info advantage or noise? | Lowers score |
| 3 | **Market Efficiency Auditor** | Real edge vs phantom edge, probability range not point estimate | Lowers score |
| 4 | **Event Archetype Engine** | Classifies event type, historical overreaction patterns | Adjusts hold period |
| 5 | **Adversarial CRO** | Destroys every trade thesis, finds fatal flaws | **Hard veto >40%** |
| 6 | **Confidence-Adjusted Kelly** | Survival-optimized position sizing | Controls dollar amount |
| 7 | **Portfolio Risk Engine** | Prevents event clustering and directional concentration | Can halve or reject |
| 8 | **Post-Trade Learning** | Two Sigma-style post-mortem on every closed trade | Improves future calls |
| 9 | **Whale Profiler** | Per-wallet category win rates, avg bet size, conviction signals | Boosts/suppresses score |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Polymarket Public APIs                        │
│   /v1/leaderboard  ·  /activity?user=  ·  /positions?user=      │
│   gamma-api.polymarket.com/markets  ·  clob.polymarket.com      │
└───────────────────────────┬─────────────────────────────────────┘
                            │ every 30 seconds
                            ▼
                  ┌─────────────────────┐
                  │   whale/monitor.py  │  ← filters top 30 leaderboard
                  │   whale/profiler.py │  ← builds per-wallet profiles
                  └──────────┬──────────┘
                             │ new trade detected
                             ▼
        ┌────────────────────────────────────────────────┐
        │              brain/committee.py                │
        │                                                │
        │  [2] Whale Intent  →  [3] Efficiency Audit     │
        │  [4] Event Archetype  →  [5] CRO Red Team ─┐  │
        │  [7] Portfolio Risk  →  [6] Kelly Sizing   │  │
        │  [1] Committee Vote  ←────────────────────-┘  │
        └───────────────────┬────────────────────────────┘
                            │ APPROVE only
                            ▼
               ┌────────────────────────┐
               │  executor/clob_client  │  ← py-clob-client on Polygon
               │  risk/kelly.py         │  ← half-Kelly, 10% hard cap
               │  risk/tp_sl_manager    │  ← TP +25% / SL -20% / 21d stop
               └────────────────────────┘
                            │
              ┌─────────────┴──────────────┐
              │                            │
              ▼                            ▼
   bot/telegram_bot.py            api.py + dashboard/
   (alerts + commands)            (FastAPI + React UI)
              │
              ▼ every 30 min (closed trades)
   scheduler/post_mortem_job → brain/committee.run_post_mortem
   → db/post_mortems (structured lessons stored permanently)
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| AI Committee | Claude Opus 4 via [Virtuals Compute API](https://virtuals.io) |
| Language | Python 3.12 |
| Whale Data | Polymarket Data API (`data-api.polymarket.com`) |
| Market Data | Polymarket Gamma API (`gamma-api.polymarket.com`) |
| Trade Execution | Polymarket CLOB API + `py-clob-client` |
| Blockchain | Polygon (MATIC) via `web3.py` |
| Scheduler | APScheduler |
| Database | SQLite (positions, signals, post-mortems, committee reports) |
| Telegram | `pyTelegramBotAPI` |
| Dashboard | React 18 + Vite + TailwindCSS + Recharts |
| API Layer | FastAPI + Uvicorn |

---

## Quickstart

### Prerequisites
- Python 3.12+
- Node.js 18+
- Virtuals API key (`acp-...` from [virtuals.io](https://virtuals.io))
- Telegram bot token (from [@BotFather](https://t.me/BotFather))

### 1. Clone & Install

```bash
git clone https://github.com/Satyam-10124/polymind-trading-agent
cd polymind-trading-agent/backend
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` — the only required fields:

```env
VIRTUALS_API_KEY=acp-your-key-here
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
TELEGRAM_CHAT_ID=your-telegram-chat-id
PAPER_MODE=true                          # keep true until validated
```

### 3. Run the Bot

```bash
# Terminal 1 — trading engine
cd backend
python main.py

# Terminal 2 — dashboard API
cd backend
uvicorn api:app --reload --port 8000

# Terminal 3 — React dashboard
cd dashboard
npm install && npm run dev
# Open http://localhost:5173
```

---

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/status` | Live bankroll, PnL, win rate, mode |
| `/positions` | All open trades with entry price + reasoning |
| `/history` | Last 10 closed trades |
| `/pause` | Halt new trade execution |
| `/resume` | Resume trading |
| `/exit_all` | Emergency close all open positions |
| `/help` | Full command list |

---

## Configuration Reference

All values live in `backend/.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `PAPER_MODE` | `true` | Simulate trades without spending USDC |
| `BANKROLL` | `50.0` | Starting capital in USDC |
| `MAX_BET_PCT` | `0.10` | Hard cap per trade (10% of bankroll) |
| `KELLY_FRACTION` | `0.5` | Half-Kelly — never full Kelly |
| `TAKE_PROFIT_PCT` | `0.25` | Exit 75% of position at +25% |
| `STOP_LOSS_PCT` | `0.20` | Full exit at -20% |
| `MIN_CLAUDE_SCORE` | `7` | Minimum committee conviction score |
| `WHALE_MIN_PNL` | `10000` | Minimum whale all-time PnL to track |
| `SCAN_INTERVAL_SECONDS` | `30` | How often to scan whale activity |
| `MAX_OPEN_POSITIONS` | `8` | Portfolio concentration limit |

---

## Going Live (Safety Checklist)

Run in paper mode for **at least 5 days** before going live.

```
□  Paper mode ran for 5+ days with >60% signal accuracy
□  Telegram alerts are working correctly
□  At least 10 Committee APPROVE decisions reviewed manually
□  Post-mortem reports are generating and making sense
□  Wallet funded: send USDC (Polygon) to your wallet address
□  Set PAPER_MODE=false in .env
□  Restart: python main.py
```

**Never put more into the wallet than you can afford to lose entirely.**

---

## Database Schema

SQLite database at `backend/polymind.db`:

| Table | Contents |
|-------|----------|
| `positions` | Every trade — open and closed, with PnL |
| `signals` | Every Claude analysis, traded or skipped |
| `committee_reports` | Full per-agent JSON reports for each trade |
| `post_mortems` | Lessons learned after each closed trade |
| `stats` | Daily performance snapshots |

---

## Revenue Model

This system generates revenue through five compounding streams:

1. **Trading profits** — direct USDC compounding on Polymarket
2. **SaaS subscriptions** — license the bot to other traders ($49/month)
3. **Signal channel** — Telegram alerts for followers ($19/month)
4. **Performance fees** — 20% of profits on managed accounts
5. **Virtuals ecosystem** — every Claude call routes through Virtuals Compute, generating platform volume and positioning for grants/features

---

## Security

- `.env` is in `.gitignore` — private key is **never committed**
- Private key is read once at startup, never logged
- Default `PAPER_MODE=true` — cannot accidentally spend real money
- All API calls use HTTPS
- No external services required beyond Polymarket public APIs + Virtuals

---

## Project Structure

```
polymarket_agent/
├── backend/
│   ├── main.py                  ← entry point, scheduler wiring
│   ├── api.py                   ← FastAPI REST for dashboard
│   ├── config.py                ← all env vars in one place
│   ├── brain/
│   │   ├── committee.py         ← 9-agent institutional pipeline
│   │   ├── claude_agent.py      ← Virtuals API wrapper
│   │   └── prompts.py           ← all 9 prompt templates
│   ├── whale/
│   │   ├── monitor.py           ← leaderboard + activity scanning
│   │   └── profiler.py          ← per-wallet intelligence profiles
│   ├── risk/
│   │   ├── kelly.py             ← confidence-adjusted Kelly sizing
│   │   └── tp_sl_manager.py     ← take profit / stop loss / time stop
│   ├── executor/
│   │   └── clob_client.py       ← CLOB order placement
│   ├── bot/
│   │   └── telegram_bot.py      ← commands + alerts
│   ├── scheduler/
│   │   └── jobs.py              ← scan + position check + post-mortem
│   └── db/
│       └── models.py            ← SQLite schema + CRUD
└── dashboard/
    └── src/
        ├── App.tsx              ← sidebar nav
        ├── pages/Dashboard.tsx  ← P&L chart + open positions
        ├── pages/Positions.tsx  ← full position history table
        └── pages/Signals.tsx    ← Claude reasoning log
```

---

## Contributing

PRs welcome. Priority areas:

- Multi-whale consensus filter (3+ whales same direction = stronger signal)
- Kalshi cross-market arbitrage detection
- Twitter/X sentiment integration
- Ensemble voting (3 parallel Claude calls, majority rules)

---

*Built on [Virtuals Compute](https://virtuals.io) — Claude Opus inference routed through the Virtuals ecosystem.*
