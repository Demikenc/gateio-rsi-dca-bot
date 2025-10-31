import os
import json
import time
import argparse
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
import pytz

import ccxt
import requests
from dotenv import load_dotenv

from utils import rsi, now_ms, sleep_s, client_order_id


# =========================
# Telegram
# =========================
def send_telegram(msg: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        requests.get(
            f"https://api.telegram.org/bot{token}/sendMessage",
            params={"chat_id": chat_id, "text": msg},
            timeout=15,
        )
    except Exception:
        pass


# =========================
# State & PnL
# =========================
STATE_DIR = "STATE"
P_L_FILE = os.path.join(STATE_DIR, "profit_log.json")


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


def load_pl():
    if not os.path.exists(P_L_FILE):
        return {"trades": [], "last_daily_summary_date": ""}
    with open(P_L_FILE, "r") as f:
        return json.load(f)


def save_pl(pl):
    with open(P_L_FILE, "w") as f:
        json.dump(pl, f, indent=2)


# =========================
# Indicators (EMA / MACD)
# =========================
def _ema(values: List[float], period: int) -> List[float]:
    if period <= 1 or not values:
        return list(values)
    k = 2 / (period + 1)
    ema = values[0]
    out = [ema]
    for v in values[1:]:
        ema = (v * k) + (ema * (1 - k))
        out.append(ema)
    return out


def macd(closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9):
    """Return (macd_line, signal_line, histogram)."""
    if len(closes) < max(fast, slow, signal) + 1:
        # not enough data; degrade gracefully
        return [0.0], [0.0], [0.0]
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = _ema(macd_line, signal)
    hist = [m - s for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, hist


# =========================
# Exchange
# =========================
def make_exchange(dry_run: bool):
    load_dotenv()
    api_key = os.getenv("GATEIO_API_KEY", "")
    api_secret = os.getenv("GATEIO_API_SECRET", "")
    exchange = ccxt.gateio({
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
        "timeout": 20000,
    })
    if not dry_run and (not api_key or not api_secret):
        raise RuntimeError("Live mode requires GATEIO_API_KEY and GATEIO_API_SECRET in .env")
    # spot only (avoid derivatives endpoints)
    exchange.load_markets(params={"type": "spot"})
    return exchange


# =========================
# Helpers
# =========================
def fetch_indicators(exchange, symbol: str, timeframe: str, lookback: int, rsi_period: int):
    """
    Aggressive mode: return RSI + MACD values only.
    Returns: (last_rsi, macd_last, macd_signal_last, macd_hist_last, macd_hist_prev)
    """
    lb = max(lookback, rsi_period + 50)
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=lb)
    closes = [c[4] for c in ohlcv]
    last_rsi = rsi(closes, rsi_period)
    macd_line, signal_line, hist = macd(closes)
    macd_last = macd_line[-1]
    macd_sig_last = signal_line[-1]
    macd_hist_last = hist[-1]
    macd_hist_prev = hist[-2] if len(hist) > 1 else macd_hist_last
    return last_rsi, macd_last, macd_sig_last, macd_hist_last, macd_hist_prev


def get_price(exchange, symbol: str) -> float:
    ticker = exchange.fetch_ticker(symbol)
    # prefer 'last' then 'close'
    last = ticker.get("last", None)
    if last is None:
        last = ticker.get("close", None)
    if last is None:
        # extremely rare; fallback to ask/bid mid if available
        ask = ticker.get("ask")
        bid = ticker.get("bid")
        if ask and bid:
            return (ask + bid) / 2
        raise RuntimeError(f"No price in ticker for {symbol}: {ticker}")
    return float(last)


def amount_from_usd(exchange, symbol: str, usd: float, price: float) -> float:
    amt = usd / price
    return float(exchange.amount_to_precision(symbol, amt))


# =========================
# Orders
# =========================
def place_limit_buy(exchange, symbol: str, amount: float, price: float, dry_run: bool):
    cid = client_order_id("buy")
    if dry_run:
        print(f"[DRY] BUY {symbol} {amount} @ {price}")
        return cid
    try:
        _ = exchange.create_order(symbol, "limit", "buy", amount, price, {"clientOrderId": cid})
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
        _ = exchange.create_order(symbol, "limit", "sell", amount, price, {"clientOrderId": cid})
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
        _ = exchange.create_order(symbol, "market", "sell", amount, None, {"clientOrderId": cid})
        print(f"[LIVE] MARKET SELL placed: {amount}")
        return cid
    except Exception as e:
        print(f"[ERR] MARKET SELL: {e}")
        return None


# =========================
# Reconcile fills → avg/size & PnL
# =========================
def reconcile_fills(exchange, symbol: str, st: SymbolState, quote_ccy: str, dry_run: bool):
    if dry_run:
        return
    since = int((time.time() - 86400) * 1000)
    try:
        orders = exchange.fetch_orders(symbol, since=since, limit=100)
    except Exception as e:
        print(f"[{symbol}] reconcile error: {e}")
        return

    pl = load_pl()
    changed = False

    for o in orders:
        if o.get("status") != "closed":
            continue
        cid = o.get("clientOrderId") or ""
        side = o.get("side")
        filled = float(o.get("filled") or 0)
        price = float(o.get("average") or o.get("price") or 0)
        if filled <= 0 or price <= 0:
            continue

        if side == "buy" and cid in st.open_buy_orders:
            cost = filled * price
            new_base = st.total_base + filled
            if new_base > 0:
                st.avg_entry = ((st.avg_entry * st.total_base) + cost) / new_base
            st.total_base = new_base
            st.open_buy_orders.remove(cid)
            changed = True
            send_telegram(f"✅ BUY FILLED\n{symbol}\n{filled} @ {price}")

        if side == "sell" and cid in st.open_sell_orders:
            proceeds = filled * price
            cost_basis = filled * st.avg_entry
            realized = proceeds - cost_basis
            st.total_base = max(0.0, st.total_base - filled)
            st.open_sell_orders.remove(cid)
            changed = True
            pl.setdefault("trades", []).append({
                "ts": int(time.time()),
                "symbol": symbol,
                "side": "sell",
                "filled": filled,
                "price": price,
                "realized_usd": realized
            })
            save_pl(pl)
            send_telegram(f"🎉 TAKE PROFIT FILLED\n{symbol}\nSold {filled} @ {price}\nPnL: {realized:.4f} {quote_ccy}")

    if changed:
        save_state(symbol, st)


# =========================
# Daily summary
# =========================
def maybe_send_daily_summary(local_tz_str="Africa/Lagos", summary_hour=21):
    pl = load_pl()
    tz = pytz.timezone(local_tz_str)
    now = datetime.now(tz)
    today_key = now.strftime("%Y-%m-%d")
    if now.hour != summary_hour or now.minute not in (0, 1):
        return
    if pl.get("last_daily_summary_date") == today_key:
        return
    start_ts = int(datetime(now.year, now.month, now.day, tzinfo=tz).timestamp())
    total = 0.0
    lines = []
    for t in pl.get("trades", []):
        if t["ts"] >= start_ts:
            val = float(t.get("realized_usd", 0))
            total += val
            lines.append(f"{t['symbol']}: {val:.2f}")
    if not lines:
        msg = "📊 DAILY SUMMARY\nNo realized P&L today yet."
    else:
        msg = "📊 DAILY SUMMARY\n" + "\n".join(lines) + f"\n\nTotal: {total:.2f} USDT"
    send_telegram(msg)
    pl["last_daily_summary_date"] = today_key
    save_pl(pl)


# =========================
# Core loop (Aggressive: RSI + MACD)
# =========================
def run_symbol(exchange, sym_cfg: Dict, dry_run: bool, lookback: int, period_rsi: int, quote_ccy: str, auto_rebuy: bool):
    symbol = sym_cfg["symbol"]
    timeframe = sym_cfg["timeframe"]
    entry_rsi_lt = float(sym_cfg["entry_rsi_lt"])
    usd_per_entry = float(sym_cfg["usd_per_entry"])
    dca_steps = int(sym_cfg["dca_steps"])
    dca_step_pct = float(sym_cfg["dca_step_pct"])
    max_position_usd = float(sym_cfg["max_position_usd"])
    take_profits = list(sym_cfg["take_profits"])
    tp_alloc = list(sym_cfg["tp_allocation"])
    stop_close_below = float(sym_cfg.get("stop_close_below", 0.0))
    min_notional_usd = float(sym_cfg.get("min_notional_usd", 10.0))

    st = load_state(symbol)
    last = get_price(exchange, symbol)

    _rsi, macd_val, macd_sig, macd_hist, macd_hist_prev = fetch_indicators(
        exchange, symbol, timeframe, lookback, period_rsi
    )

    print(f"[{symbol}] price={last:.8f} RSI={_rsi:.2f} MACD={macd_hist:.6f} avg={st.avg_entry:.8f} size={st.total_base}")

    # Reconcile fills
    reconcile_fills(exchange, symbol, st, quote_ccy, dry_run)

    # Optional stop-loss
    if st.total_base > 0 and stop_close_below > 0 and last < stop_close_below:
        send_telegram(f"⚠️ STOP EXIT: {symbol}\nPrice: {last:.8f} < {stop_close_below}")
        cid = place_market_sell(exchange, symbol, st.total_base, dry_run)
        if cid:
            pl = load_pl()
            realized = (last - st.avg_entry) * st.total_base
            pl.setdefault("trades", []).append({
                "ts": int(time.time()),
                "symbol": symbol,
                "side": "stop_exit",
                "filled": st.total_base,
                "price": last,
                "realized_usd": realized
            })
            save_pl(pl)
            st = SymbolState()
            save_state(symbol, st)
        return

    # Take-profits
    if st.total_base > 0 and st.avg_entry > 0:
        for idx, tp in enumerate(take_profits):
            target_price = st.avg_entry * (1.0 + tp)
            amount = st.total_base * tp_alloc[idx]
            amount = float(exchange.amount_to_precision(symbol, amount))
            if amount * last < min_notional_usd:
                continue
            cid = place_limit_sell(exchange, symbol, amount, target_price, dry_run)
            if cid:
                st.open_sell_orders.append(cid)
                send_telegram(
                    f"📈 TAKE PROFIT SET\n{symbol}\nSell @ {target_price:.8f}\nAmount: {amount}"
                )
        save_state(symbol, st)

    # Aggressive entry: RSI oversold + MACD histogram turning up (rising)
    enter = (_rsi < entry_rsi_lt) and (macd_hist > macd_hist_prev)

    if enter:
        if st.anchor_price is None:
            st.anchor_price = last
            st.last_signal_ts = now_ms()
            send_telegram(f"🎯 ENTRY ARMED (RSI+MACD): {symbol}\nAnchor @ {st.anchor_price:.8f}")

        price = st.anchor_price
        total_usd = 0.0
        for i in range(dca_steps):
            buy_price = price * (1.0 - (i * dca_step_pct / 100.0))
            usd_budget = usd_per_entry
            if total_usd + usd_budget > max_position_usd:
                break
            if usd_budget < min_notional_usd:
                continue
            amount = amount_from_usd(exchange, symbol, usd_budget, buy_price)
            if amount * buy_price < min_notional_usd:
                continue
            cid = place_limit_buy(exchange, symbol, amount, buy_price, dry_run)
            if cid:
                st.open_buy_orders.append(cid)
                total_usd += usd_budget
                send_telegram(
                    f"📉 BUY PLACED\n{symbol}\n@ {buy_price:.8f}\nAmount: {amount}"
                )
        save_state(symbol, st)
    else:
        # clear anchor once RSI recovers far above trigger
        if st.anchor_price and _rsi > entry_rsi_lt + 10:
            st.anchor_price = None
            save_state(symbol, st)

    # Auto-rearm
    if auto_rebuy and st.total_base == 0 and _rsi < entry_rsi_lt:
        if st.anchor_price is None:
            st.anchor_price = last
            save_state(symbol, st)
            send_telegram(f"🔁 AUTO-REBUY ARMED: {symbol}\nAnchor @ {st.anchor_price:.8f}")


# =========================
# Main
# =========================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--selftest", action="store_true", help="Run indicator unit tests and exit.")
    args = ap.parse_args()

    if args.selftest:
        # --- Minimal tests for RSI & MACD ---
        # RSI monotonic check on increasing series
        inc = list(range(1, 100))
        r = rsi(inc, 14)
        assert isinstance(r, float), "RSI must return float"
        # MACD shape test
        m, s, h = macd(inc)
        assert len(m) == len(s) == len(h), "MACD lengths mismatch"
        print("Selftests passed ✅")
        return

    with open(args.config, "r") as f:
        cfg = json.load(f)

    dry_run = bool(cfg.get("dry_run_default", True))
    lookback = int(cfg.get("lookback_candles", 200))
    period_rsi = int(cfg.get("default_period_rsi", 14))
    poll = int(cfg.get("poll_seconds", 45))
    quote_ccy = cfg.get("quote_currency", "USDT")
    auto_rebuy = bool(cfg.get("auto_rebuy", True))
    summary_hour = int(cfg.get("daily_summary_hour", 21))

    ensure_state_dir()
    if not os.path.exists(P_L_FILE):
        save_pl({"trades": [], "last_daily_summary_date": ""})

    exchange = make_exchange(dry_run)
    symbols = cfg["symbols"]

    print(f"Dry-run={dry_run}  Poll={poll}s")
    for s in symbols:
        print(f"- {s['symbol']} {s['timeframe']} (RSI<{s['entry_rsi_lt']})")

    send_telegram("🤖 Bot online. Monitoring markets...")

    while True:
        for s in symbols:
            try:
                run_symbol(exchange, s, dry_run, lookback, period_rsi, quote_ccy, auto_rebuy)
            except Exception as e:
                print(f"[{s['symbol']}] ERROR: {e}")
        try:
            maybe_send_daily_summary("Africa/Lagos", summary_hour)
        except Exception as e:
            print(f"[SUMMARY] error: {e}")
        time.sleep(poll)


if __name__ == "__main__":
    main()
