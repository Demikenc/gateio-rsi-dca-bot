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
