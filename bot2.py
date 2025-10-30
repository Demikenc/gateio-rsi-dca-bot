import os
import json
import time
import argparse
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import ccxt
import requests
from dotenv import load_dotenv

from utils import rsi, now_ms, sleep_s, client_order_id

# ==============================================
# TELEGRAM ALERT FUNCTION
# ==============================================
def send_telegram(msg: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        requests.get(f"https://api.telegram.org/bot{token}/sendMessage",
                     params={"chat_id": chat_id, "text": msg})
    except Exception:
        pass

STATE_DIR = "STATE"

@dataclass
class SymbolState:
    avg_entry: float = 0.0
    total_base: float = 0.0
    open_buy_orders: List[str] = field(default_factory=list)
    open_sell_orders: List[str] = field(default_factory=list)
    anchor_price: Optional[float] = None
    last_signal_ts: int = 0

def ensure_state_dir():
    if not os.path.exists(STATE_DIR):
        os.makedirs(STATE_DIR, exist_ok=True)

def state_path(sym: str) -> str:
    safe = sym.replace("/", "_")
    return os.path.join(STATE_DIR, f"{safe}.json")

def load_state(sym: str) -> SymbolState:
    p = state_path(sym)
    if not os.path.exists(p):
        return SymbolState()
    with open(p, "r") as f:
        data = json.load(f)
    return SymbolState(**data)

def save_state(sym: str, st: SymbolState):
    with open(state_path(sym), "w") as f:
        json.dump(st.__dict__, f, indent=2)

def make_exchange(dry_run: bool):
    load_dotenv()
    api_key = os.getenv("GATEIO_API_KEY", "")
    api_secret = os.getenv("GATEIO_API_SECRET", "")
    exchange = ccxt.gateio({
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
    if not dry_run and (not api_key or not api_secret):
        raise RuntimeError("Live mode requires GATEIO_API_KEY and GATEIO_API_SECRET in .env")
    exchange.load_markets()
    return exchange

def fetch_rsi(exchange, symbol: str, timeframe: str, lookback: int, period: int) -> float:
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=period + 50)
    closes = [c[4] for c in ohlcv]
    return rsi(closes, period)

def get_price(exchange, symbol: str) -> float:
    ticker = exchange.fetch_ticker(symbol)
    return ticker["last"] or ticker["close"]

def place_limit_buy(exchange, symbol: str, amount: float, price: float, dry_run: bool):
    cid = client_order_id("buy")
    if dry_run:
        print(f"[DRY] BUY {symbol} {amount} @ {price}")
        return cid
    try:
        o = exchange.create_order(symbol, "limit", "buy", amount, price, {"clientOrderId": cid})
        print(f"[LIVE] BUY placed: {amount} @ {price}")
        return cid
    except Exception as e:
        print(f"[ERR] BUY: {e}")
        return None

def place_limit_sell(exchange, symbol: str, amount: float, price: float, dry_run: bool):
    cid = client_order_id("sell")
    if dry_run:
        print(f"[DRY] SELL {symbol} {amount} @ {price}")
        return cid
    try:
        o = exchange.create_order(symbol, "limit", "sell", amount, price, {"clientOrderId": cid})
        print(f"[LIVE] SELL placed: {amount} @ {price}")
        return cid
    except Exception as e:
        print(f"[ERR] SELL: {e}")
        return None

def place_market_sell(exchange, symbol: str, amount: float, dry_run: bool):
    cid = client_order_id("mksell")
    if dry_run:
        print(f"[DRY] MARKET SELL {symbol} {amount}")
        return cid
    try:
        o = exchange.create_order(symbol, "market", "sell", amount, None, {"clientOrderId": cid})
        print(f"[LIVE] MARKET SELL placed: {amount}")
        return cid
    except Exception as e:
        print(f"[ERR] MARKET SELL: {e}")
        return None

def amount_from_usd(exchange, symbol: str, usd: float, price: float) -> float:
    amt = usd / price
    return float(exchange.amount_to_precision(symbol, amt))

def run_symbol(exchange, sym_cfg, dry_run, lookback, period_rsi):
    symbol = sym_cfg["symbol"]
    timeframe = sym_cfg["timeframe"]
    entry_rsi_lt = sym_cfg["entry_rsi_lt"]
    usd_per_entry = sym_cfg["usd_per_entry"]
    dca_steps = sym_cfg["dca_steps"]
    dca_step_pct = sym_cfg["dca_step_pct"]
    max_position_usd = sym_cfg["max_position_usd"]
    take_profits = sym_cfg["take_profits"]
    tp_alloc = sym_cfg["tp_allocation"]
    stop_close_below = sym_cfg["stop_close_below"]
    min_notional_usd = sym_cfg["min_notional_usd"]

    st = load_state(symbol)
    last = get_price(exchange, symbol)
    _rsi = fetch_rsi(exchange, symbol, timeframe, lookback, period_rsi)

    print(f"[{symbol}] price={last:.8f} RSI={_rsi:.2f} avg={st.avg_entry:.8f} size={st.total_base}")

    # STOP EXIT
    if st.total_base > 0 and last < stop_close_below:
        send_telegram(f"⚠️ STOP EXIT: {symbol}\nPrice: {last}")
        place_market_sell(exchange, symbol, st.total_base, dry_run)
        st = SymbolState()
        save_state(symbol, st)
        return

    # TAKE PROFIT
    if st.total_base > 0 and st.avg_entry > 0:
        for idx, tp in enumerate(take_profits):
            target_price = st.avg_entry * (1 + tp)
            amount = st.total_base * tp_alloc[idx]
            if amount * last < min_notional_usd:
                continue
            cid = place_limit_sell(exchange, symbol, amount, target_price, dry_run)
            if cid:
                send_telegram(f"📈 TAKE PROFIT SET\n{symbol}\nSell @ {target_price:.8f}\nAmount: {amount}")
        save_state(symbol, st)

    # BUY SIGNAL
    if _rsi < entry_rsi_lt:
        if st.anchor_price is None:
            st.anchor_price = last
            send_telegram(f"🎯 BUY SIGNAL: {symbol}\nAnchor @ {last}")
        price = st.anchor_price
        total = 0.0
        for i in range(dca_steps):
            buy_price = price * (1 - (i * dca_step_pct / 100))
            if total + usd_per_entry > max_position_usd:
                break
            amount = amount_from_usd(exchange, symbol, usd_per_entry, buy_price)
            cid = place_limit_buy(exchange, symbol, amount, buy_price, dry_run)
            if cid:
                total += usd_per_entry
                send_telegram(f"📉 BUY PLACED\n{symbol}\nPrice {buy_price:.8f}\nAmount {amount}")

        if total > 0:
            st.avg_entry = buy_price
            st.total_base += amount_from_usd(exchange, symbol, total, buy_price)
            save_state(symbol, st)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    args = ap.parse_args()

    with open(args.config, "r") as f:
        cfg = json.load(f)

    dry_run = cfg.get("dry_run_default", True)
    lookback = cfg["lookback_candles"]
    period_rsi = cfg["default_period_rsi"]
    poll = cfg["poll_seconds"]

    ensure_state_dir()
    exchange = make_exchange(dry_run)
    symbols = cfg["symbols"]

    while True:
        for s in symbols:
            try:
                run_symbol(exchange, s, dry_run, lookback, period_rsi)
            except Exception as e:
                print(f"[{s['symbol']}] ERROR: {e}")
        sleep_s(poll)

if __name__ == "__main__":
    main()
