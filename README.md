# PolyMind — Autonomous Polymarket Trading Agent

AI-powered trading bot that watches top Polymarket whales, filters trades through Claude Opus reasoning, and executes USDC bets with Kelly sizing and early TP/SL exits.

---

## Your Wallet
- **Address:** `0x62A8cAbc0E77BCE7f1B2D1030f1c04511a649D43`
- **Network:** Polygon (MATIC)
- **Deposit:** Send USDC (Polygon) to the address above to fund trading

---

## Setup (5 steps)

### 1. Install Python dependencies
```bash
cd backend
pip install -r requirements.txt
```

### 2. Configure environment
Edit `backend/.env`:
```
TELEGRAM_BOT_TOKEN=   ← get from @BotFather on Telegram
TELEGRAM_CHAT_ID=     ← get from @userinfobot on Telegram
PAPER_MODE=true       ← keep true until you verify it works
```

### 3. Run the bot
```bash
cd backend
python main.py
```

### 4. Install and run the dashboard
```bash
cd dashboard
npm install
npm run dev
# Open http://localhost:5173
```

### 5. Run the FastAPI layer (for dashboard data)
```bash
cd backend
uvicorn api:app --reload --port 8000
```

---

## Telegram Commands
| Command | Action |
|---------|--------|
| `/status` | Bankroll, PnL, win rate |
| `/positions` | Open positions |
| `/history` | Last 10 trades |
| `/pause` | Stop trading |
| `/resume` | Resume trading |
| `/exit_all` | Emergency close all |

---

## Go Live Checklist
1. Run paper mode for 5+ days
2. Verify Claude signals are sensible
3. Set `PAPER_MODE=false` in `.env`
4. Fund wallet: send USDC to `0x62A8cAbc0E77BCE7f1B2D1030f1c04511a649D43`
5. Restart bot

---

## Architecture
```
Polymarket Leaderboard API
  → whale/monitor.py        (detect new whale trades)
  → brain/claude_agent.py   (Claude Opus via Virtuals — score 1-10)
  → risk/kelly.py           (half-Kelly bet sizing)
  → executor/clob_client.py (place order via CLOB)
  → risk/tp_sl_manager.py   (exit at +25% / -20%)
  → bot/telegram_bot.py     (alerts + commands)
  → api.py + dashboard/     (React dashboard)
```

---

## Security
- Never commit `.env` — it contains your private key
- Private key is only in `.env` and never logged
- Start with PAPER_MODE=true, add real USDC only after validation
