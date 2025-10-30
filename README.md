# Gate.io RSI+DCA Swing Bot (Spot)
A practical, production-ready trading bot for Gate.io that:
- Buys dips when RSI(14) is below a threshold
- Places a DCA ladder (multiple staggered limit buys)
- Takes profit automatically with one or more targets
- Exits if the trend breaks (configurable stop)
- Supports **dry-run** mode (no orders are sent) for safe testing

## Features
- Exchange: Gate.io (via `ccxt`)
- Markets: Spot (e.g., BTC/USDT, ETH/USDT, JTO/USDT)
- Timeframes: 1h / 4h (configurable)
- Config-first: All parameters live in `config.json`
- Safe: Rate-limit aware, retries, idempotent order client IDs
- Portable: Works on Windows, macOS, Linux (Python 3.10+)

---

## Quick Start
1) **Install Python** 3.10 or newer.

2) **Clone / unzip** this folder locally.

3) In a terminal from this folder:
```bash
pip install -r requirements.txt
cp .env.example .env  # then edit .env with your Gate.io keys
```

4) **Edit `config.json`** — pick symbols, timeframes, RSI triggers, TP %, DCA ladder, etc.

5) **Dry Run First** (recommended):
```bash
python bot.py --dry-run
```

6) **Go Live** (real orders):
```bash
python bot.py
```

> Tip: run it forever with `screen`/`tmux`, or set up a systemd service on Linux. On Windows, use `pythonw.exe` + Task Scheduler.

---

## Gate.io API Keys
- Create keys: Gate.io ➜ API Management ➜ Create V4 keys (trading enabled).
- Copy them into `.env`:
```
GATEIO_API_KEY=your_key_here
GATEIO_API_SECRET=your_secret_here
```
*(No passphrase needed for ccxt Gate.io spot.)*

> **Never** commit your keys to Git. `.env` is excluded via `.gitignore`.

---

## Risk Notes
- Use **dry-run** until you're comfortable.
- Start with **small sizes**. This is a swing strategy, not scalping.
- Markets can gap; stops may slip. Nothing is guaranteed.
- You are responsible for your capital.

---

## Strategy Defaults (from our analysis)
- BTC/USDT 4h: buy when RSI < 38, TP +6%/+11%, exit if close < 105000 (override in config)
- ETH/USDT 4h: buy when RSI < 36, TP +8%, exit if close < 3700
- JTO/USDT 1h: buy when RSI < 35, TP +12% (partials allowed), exit if close < 1.62

You can fully customize these in `config.json`.

---

## Files
- `bot.py` — main runner
- `config.json` — per-symbol settings
- `requirements.txt` — Python deps
- `.env.example` — API key template
- `utils.py` — helpers (RSI, retries, math)
- `STATE/` — persisted state (average entry, open order IDs, logs)

---

## Common Commands
Dry-run verbose:
```bash
python bot.py --dry-run --once
```

Live, loop forever:
```bash
python bot.py --loop
```

Run only specific symbol:
```bash
python bot.py --symbols BTC/USDT ETH/USDT
```

---

## Troubleshooting
- `ccxt.errors.NetworkError`: transient; the bot retries. Check internet/time sync.
- `DDoSProtection`: reduce frequency via `poll_seconds` in config.
- `InsufficientFunds`: decrease `usd_per_entry` or DCA steps.
- `ExchangeError: min notional`: Gate.io enforces min order sizes—raise `min_notional_usd` for that symbol.

---

## License
MIT — use at your own risk.
