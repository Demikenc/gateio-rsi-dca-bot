from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import os, json, time
from datetime import datetime, timezone
from typing import Dict, Any, List
import ccxt

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(APP_DIR, "STATE")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
PL_PATH = os.path.join(STATE_DIR, "profit_log.json")

app = FastAPI(title="Trading Dashboard")
templates = Jinja2Templates(directory=os.path.join(APP_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(APP_DIR, "static")), name="static")

def load_config() -> Dict[str, Any]:
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {"quote_currency":"USDT","symbols":[{"symbol":"PEPE/USDT"},{"symbol":"JTO/USDT"}]}

def load_state_for(symbol: str) -> Dict[str, Any]:
    safe = symbol.replace("/", "_")
    path = os.path.join(STATE_DIR, f"{safe}.json")
    if not os.path.exists(path):
        return {"avg_entry": 0.0, "total_base": 0.0}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {"avg_entry": 0.0, "total_base": 0.0}

def load_profit_log() -> Dict[str, Any]:
    if not os.path.exists(PL_PATH):
        return {"trades": []}
    try:
        with open(PL_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {"trades": []}

def make_public_exchange():
    ex = ccxt.gateio({"enableRateLimit": True, "options": {"defaultType": "spot"}})
    ex.timeout = 20000
    try:
        ex.load_markets(params={"type":"spot"})
    except Exception:
        pass
    return ex

EXCHANGE = make_public_exchange()

def get_last_price(symbol: str) -> float:
    try:
        t = EXCHANGE.fetch_ticker(symbol)
        return float(t.get("last") or t.get("close") or 0.0)
    except Exception:
        return 0.0

def realized_today_usd(pl: Dict[str, Any]) -> float:
    now = datetime.now(timezone.utc)
    start = datetime(year=now.year, month=now.month, day=now.day, tzinfo=timezone.utc).timestamp()
    total = 0.0
    for t in pl.get("trades", []):
        try:
            if float(t.get("ts", 0)) >= start:
                total += float(t.get("realized_usd", 0.0))
        except Exception:
            continue
    return total

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    cfg = load_config()
    symbols = [s["symbol"] for s in cfg.get("symbols", [])]
    return templates.TemplateResponse("index.html", {"request": request, "symbols": symbols})

@app.get("/api/status")
async def status():
    cfg = load_config()
    out: List[Dict[str, Any]] = []
    for s in cfg.get("symbols", []):
        sym = s["symbol"]
        st = load_state_for(sym)
        price = get_last_price(sym)
        avg = float(st.get("avg_entry", 0.0) or 0.0)
        base = float(st.get("total_base", 0.0) or 0.0)
        unrealized = 0.0
        unrealized_pct = 0.0
        if base > 0 and avg > 0 and price > 0:
            unrealized = (price - avg) * base
            unrealized_pct = ((price / avg) - 1.0) * 100.0
        out.append({
            "symbol": sym,
            "price": price,
            "avg_entry": avg,
            "position": base,
            "unrealized_usd": unrealized,
            "unrealized_pct": unrealized_pct
        })
    pl = load_profit_log()
    return JSONResponse({"symbols": out, "realized_today_usd": realized_today_usd(pl), "server_time": int(time.time())})
