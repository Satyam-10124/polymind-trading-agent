# PolyMind — Autonomous Polymarket Trading Agent
## Complete Product Plan

---

## 1. What It Is

A fully autonomous trading agent that:
- Scans Polymarket 24/7 for mispriced prediction markets
- Uses Claude Opus (via Virtuals Compute API) to reason like a Bloomberg quant
- Places real USDC bets on Polygon via the CLOB API
- **Exits positions early** (sell at 75¢ if bought at 60¢ — no waiting for resolution)
- Controls everything via Telegram
- Shows live P&L on a React dashboard

---

## 2. Reference Repos (Study These)

| Repo | Why |
|------|-----|
| `github.com/Polymarket/agents` | Official — market scanner + LLM trades |
| `github.com/skharchikov/polymarket-bot` | Best signals — XGBoost + Kelly + Telegram + self-retrain |
| `github.com/guberm/polymarket-bot` | Claude/Gemini ensemble + Kelly — Python |
| `github.com/alsk1992/CloddsBot` | Claude terminal — chat-driven trading |
| `github.com/RobotTraders/bits_and_bobs` | polymarket_ai_bot.py — simplest reference |
| `github.com/Polymarket/py-clob-client` | Official Python CLOB SDK |

---

## 3. Full Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        POLYMIND                             │
├──────────────┬──────────────┬──────────────┬───────────────┤
│   SCANNER    │    BRAIN     │   EXECUTOR   │   GUARDIAN    │
│              │              │              │               │
│ Gamma API    │ Claude Opus  │ CLOB API     │ Risk Manager  │
│ every 15min  │ Virtuals API │ Polygon Web3 │ TP/SL engine  │
│              │ web_search   │ limit orders │ Kelly sizer   │
│ Filters:     │              │ early exits  │ correlation   │
│ vol > $5k    │ → YES/NO     │              │ checker       │
│ price 10-90¢ │ → confidence │ place_order()│               │
│ expiry 2-30d │ → edge %     │ cancel_order │ max 10% per   │
│ not sports   │ → reasoning  │ get_positions│ trade         │
├──────────────┴──────────────┴──────────────┴───────────────┤
│                    DATA LAYER                               │
│   PostgreSQL (trades) · Redis (prices) · SQLite (signals)  │
├─────────────────────────────────────────────────────────────┤
│                 INTERFACES                                  │
│   Telegram Bot · React Dashboard · FastAPI REST            │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Tech Stack

### Backend
- **Python 3.12** — core engine
- **FastAPI** — REST API layer
- **py-clob-client** — Polymarket CLOB SDK
- **web3.py** — Polygon wallet + on-chain signing
- **anthropic** SDK — Claude Opus via Virtuals API
- **python-telegram-bot** — Telegram interface
- **APScheduler** — cron jobs (scan, position check, retrain)
- **SQLAlchemy + PostgreSQL** — trade history, positions
- **Redis** — live price cache, orderbook snapshots
- **XGBoost + scikit-learn** — ML signal layer (trained on resolved markets)

### Frontend Dashboard
- **React 18 + TypeScript + Vite**
- **TailwindCSS** — dark quant terminal theme
- **Recharts** — P&L curves, win rate, Brier score
- **React Query** — live data from FastAPI

### Infrastructure
- **Docker Compose** — runs everything locally
- **Vercel** — dashboard deploy
- **Railway / VPS** — backend 24/7

---

## 5. Project Folder Structure

```
polymarket_agent/
├── backend/
│   ├── main.py                  # FastAPI app entry
│   ├── config.py                # env vars, constants
│   ├── scanner/
│   │   ├── gamma_client.py      # Polymarket Gamma API
│   │   ├── market_filter.py     # volume/price/expiry filters
│   │   └── feature_engine.py   # 29 ML features per market
│   ├── brain/
│   │   ├── claude_agent.py      # Claude Opus via Virtuals API
│   │   ├── master_prompts.py    # Bloomberg-level prompts
│   │   └── signal_builder.py   # combine ML + LLM signal
│   ├── executor/
│   │   ├── clob_client.py       # CLOB order placement
│   │   ├── position_manager.py  # open/close positions
│   │   └── wallet.py            # Polygon wallet signing
│   ├── risk/
│   │   ├── kelly.py             # Kelly criterion sizing
│   │   ├── tp_sl_manager.py    # take profit / stop loss
│   │   └── portfolio.py         # correlation, exposure
│   ├── bot/
│   │   └── telegram_bot.py      # Telegram commands
│   ├── db/
│   │   ├── models.py            # SQLAlchemy models
│   │   └── crud.py              # DB operations
│   └── scheduler/
│       └── jobs.py              # scan/check/retrain jobs
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx    # P&L overview
│   │   │   ├── Positions.tsx    # open positions
│   │   │   ├── History.tsx      # closed trades
│   │   │   └── Signals.tsx      # Claude reasoning log
│   │   └── components/
├── ml/
│   ├── train.py                 # train on resolved markets
│   └── features.py              # feature extraction
├── .env.example
├── docker-compose.yml
└── README.md
```

---

## 6. The Quant Trading Algorithm

### Step 1 — Market Scan (every 15 min)
```python
filters = {
    "min_volume": 5000,          # enough liquidity
    "min_price": 0.10,           # not near-certain
    "max_price": 0.90,           # not near-certain
    "min_days_to_expiry": 2,     # time to play out
    "max_days_to_expiry": 30,    # not too far out
    "block_sports": True,        # sports = sharp bettors dominate
    "min_order_book_depth": 500, # enough to exit early
}
```

### Step 2 — ML Pre-filter (XGBoost)
29 features computed per market:
- Price momentum (1h, 24h), volatility, RSI
- Log volume, days to expiry, order book depth
- NLP features from question text (certainty, numbers, dates)
- Sentiment score

Only top 15 candidates sent to Claude (saves API cost).

### Step 3 — Claude Opus Analysis
See Master Prompts section below.

### Step 4 — Kelly Criterion Sizing
```
edge      = claude_prob - market_price
kelly_f   = edge / (1 - market_price)  # for YES side
half_kelly = kelly_f * 0.5              # always use half-Kelly
bet_size  = bankroll * half_kelly
bet_size  = min(bet_size, bankroll * 0.10)  # hard cap 10%
```

### Step 5 — Early Exit Engine (TP/SL)
**This is the key feature — sell before resolution:**
```python
# Every 10 minutes, check all open positions
for position in open_positions:
    current_price = get_clob_price(position.market_id)
    entry_price   = position.entry_price

    pnl_pct = (current_price - entry_price) / entry_price

    # Take Profit: +20% move → sell 75% of position
    if pnl_pct >= 0.20:
        sell_partial(position, qty=0.75)

    # Take Profit: +40% move → sell rest
    if pnl_pct >= 0.40:
        sell_all(position)

    # Stop Loss: -30% move → exit fully
    if pnl_pct <= -0.30:
        sell_all(position)

    # Time Stop: 3 days before expiry, price < 50¢ → exit
    if days_to_expiry(position) <= 3 and current_price < 0.50:
        sell_all(position)
```
On CLOB, selling = placing a SELL limit order at current best bid.
Your YES tokens at 60¢ become SELL orders at 75¢ — filled when someone buys.

---

## 7. Master Prompts (Bloomberg/JPM Level)

### Market Analysis Prompt
```
SYSTEM:
You are PolyMind, an elite quantitative analyst trained on Bloomberg
Terminal data, JPMorgan research methodology, and Superforecaster
calibration techniques. You reason like a combination of Nate Silver,
Renaissance Technologies, and a Goldman Sachs macro strategist.

Your job: evaluate ONE binary prediction market question and determine
if the current market price represents exploitable mispricing.

RULES:
1. Search the web for the 3 most recent, relevant facts about this question
2. Identify the BASE RATE — how often do similar events historically occur?
3. Apply Bayesian updating: start from base rate, update with recent evidence
4. Account for: market bias, narrative overcorrection, recency bias in crowd
5. Your confidence must be CALIBRATED — if you say 70%, you should be right 70%
6. You are risking REAL MONEY. Do NOT trade unless edge is clear and defensible
7. Refuse to trade if: sports event, >3 correlated positions already open,
   or insufficient recent information found

OUTPUT ONLY via the structured tool — no prose.

USER:
Market: {question}
Current YES price: {price}¢ (implied prob: {price}%)
Volume: ${volume:,} | Days to expiry: {days}
Category: {category}

Analyse this market. Find recent news. Give your probability estimate.
```

### Tool Schema (structured output)
```python
ANALYSIS_TOOL = {
    "name": "trade_decision",
    "input_schema": {
        "type": "object",
        "properties": {
            "my_probability":  {"type": "number", "min": 0, "max": 1},
            "market_price":    {"type": "number"},
            "edge":            {"type": "number"},  # my_prob - market_price
            "direction":       {"type": "string", "enum": ["YES", "NO", "SKIP"]},
            "confidence":      {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
            "reasoning":       {"type": "string", "maxLength": 500},
            "key_facts":       {"type": "array", "items": {"type": "string"}},
            "base_rate":       {"type": "string"},
            "risks":           {"type": "string"},
        },
        "required": ["my_probability", "direction", "confidence", "reasoning",
                     "key_facts", "base_rate", "risks"]
    }
}

# Only trade when:
# confidence == "HIGH" AND abs(edge) >= 0.08 (8 cents of edge minimum)
```

### Daily Performance Review Prompt
```
You are a risk officer reviewing yesterday's trading performance.
Given these trades: {trade_log}

1. Which trades showed good/poor reasoning?
2. Where was the model overconfident vs underconfident?
3. What patterns should be avoided tomorrow?
4. Suggested parameter adjustments?

Be brutally honest. Capital preservation is priority one.
```

---

## 8. Telegram Bot Commands

```
/status        — current bankroll, open positions, today's P&L
/positions     — list all open positions with current prices
/scan          — trigger manual market scan now
/pause         — pause auto-trading
/resume        — resume auto-trading
/exit_all      — emergency close all positions at market
/history       — last 20 trades with outcomes
/performance   — win rate, ROI, Brier score, Sharpe ratio
/risk          — current exposure, Kelly fractions
/setlimit $X   — set max bet size
/report        — full daily P&L report PDF
```

Telegram sends alerts automatically on:
- New trade opened: `🟢 BOUGHT YES: "Will BTC hit $120k?" @ 34¢ — size: $8.20`
- TP hit: `💰 SOLD: +25% — locked $2.05 profit`
- SL hit: `🔴 STOPPED: -30% — lost $3.10, saved $7.00`
- Daily summary at 9pm

---

## 9. React Dashboard Pages

### Dashboard (home)
- Total bankroll + today's P&L (big number, color coded)
- P&L curve (last 30 days, Recharts line)
- Win rate gauge, avg ROI per trade, Sharpe ratio
- Active positions table (live price updates via SSE)
- Recent Claude reasoning log

### Positions
- All open positions: market, entry price, current price, unrealized P&L
- TP/SL levels shown as price targets
- One-click manual exit button

### Trade History
- All closed trades with full Claude reasoning
- Filter by date, outcome, category
- Export CSV

### Signals Log
- Full Claude Opus reasoning for every analysed market
- Shows markets that were analysed but rejected (SKIP) too
- Searchable

---

## 10. Risk Rules (Hard-Coded, Non-Negotiable)

```python
MAX_SINGLE_BET_PCT    = 0.10   # max 10% of bankroll per trade
MAX_OPEN_POSITIONS    = 8      # never hold more than 8 at once
MIN_EDGE_TO_TRADE     = 0.08   # 8¢ minimum edge
MIN_LIQUIDITY         = 500    # $500 order book depth to ensure exit
BLOCK_SPORTS          = True   # sharp bettors own sports markets
KELLY_FRACTION        = 0.5    # half-Kelly always
TAKE_PROFIT_1         = 0.20   # sell 75% at +20%
TAKE_PROFIT_2         = 0.40   # sell rest at +40%
STOP_LOSS             = -0.30  # exit at -30%
MAX_DAYS_HOLD         = 21     # exit any position after 21 days
MAX_CORRELATED_BETS   = 2      # max 2 bets in same category
```

---

## 11. $50 Bankroll Game Plan

### Week 1 — Paper trading
- Run bot in paper mode (logs trades, never sends to CLOB)
- Target: 5+ paper trades, track accuracy
- Need: >55% win rate to continue

### Week 2 — Go live
- Deploy with $50 USDC on Polygon
- Half-Kelly on $50 = max $5 per trade
- Target: 10+ real trades

### Month 1 milestones
```
Start:   $50
Week 2:  $55-65 if model is working
Week 4:  $70-90 if sustained edge
Month 2: Add $200 → scale up position sizes
```

---

## 12. APIs & Keys You Need

| Credential | Where to get |
|-----------|-------------|
| `VIRTUALS_API_KEY` | compute.virtuals.io (you have this) |
| `POLYMARKET_PRIVATE_KEY` | MetaMask → export private key |
| `POLYMARKET_FUNDER_ADDRESS` | your MetaMask wallet address |
| `TELEGRAM_BOT_TOKEN` | @BotFather on Telegram |
| `TELEGRAM_CHAT_ID` | @userinfobot on Telegram |

Virtuals API base: `https://compute.virtuals.io/v1`
Model: use `claude-opus` or equivalent from your Virtuals model list

---

## 13. Build Order (What to Build First)

1. `scanner/gamma_client.py` — fetch markets, apply filters
2. `brain/claude_agent.py` — call Virtuals API with master prompt
3. `executor/clob_client.py` — wrap py-clob-client, place/cancel orders
4. `risk/kelly.py + tp_sl_manager.py` — sizing + exit logic
5. `scheduler/jobs.py` — wire it all together on a timer
6. `bot/telegram_bot.py` — /status, /pause, /exit_all commands
7. `backend/main.py` — FastAPI endpoints for dashboard
8. `frontend/` — React dashboard

**Say "start building" and I'll write the full code, file by file.**
