import time
import math
import hashlib
import random
from typing import List

def rsi(values: List[float], period: int = 14) -> float:
    """Compute RSI(14) from a list of closing prices."""
    if len(values) < period + 1:
        return float("nan")
    gains = []
    losses = []
    for i in range(1, period + 1):
        diff = values[-i] - values[-i - 1]
        if diff >= 0:
            gains.append(diff)
        else:
            losses.append(-diff)
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def now_ms():
    return int(time.time() * 1000)

def sleep_s(seconds: int):
    time.sleep(seconds)

def client_order_id(prefix: str) -> str:
    base = f"{prefix}-{int(time.time()*1000)}-{random.randint(1000,9999)}"
    h = hashlib.sha1(base.encode()).hexdigest()[:10]
    return f"{prefix}-{h}"

def round_step(value: float, step: float) -> float:
    """Round value to the nearest exchange step size."""
    return math.floor(value / step) * step

def pct(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return (a - b) / b * 100.0
def macd(series, fast=12, slow=26, signal=9):
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = [f - s for f, s in zip(fast_ema, slow_ema)]
    signal_line = ema(macd_line, signal)
    hist = [m - s for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, hist

def ema(values, period):
    alpha = 2 / (period + 1)
    ema_vals = []
    for i, v in enumerate(values):
        if i == 0:
            ema_vals.append(v)
        else:
            ema_vals.append((v - ema_vals[-1]) * alpha + ema_vals[-1])
    return ema_vals

