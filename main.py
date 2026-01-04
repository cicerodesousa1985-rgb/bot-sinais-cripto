import os
import time
import threading
import requests
import logging
from datetime import datetime
from flask import Flask

# =========================
# CONFIGURAÇÃO
# =========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

signals_paused = False
last_signals = []

# =========================
# CACHE & HISTÓRICO
# =========================
indicator_history = {}   # (symbol, timeframe)
kline_cache = {}         # (symbol, timeframe)
CACHE_TTL = 30

# =========================
# CONFIGURAÇÃO DO BOT
# =========================
TIMEFRAMES = ["1m", "5m", "15m"]

PAIRS = [
    "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","AVAXUSDT",
    "DOGEUSDT","DOTUSDT","TRXUSDT","LINKUSDT","MATICUSDT","LTCUSDT"
]

STRATEGIES = {
    "RSI_EXTREME": {"active": True},
    "STOCH_FAST": {"active": True},
    "PRICE_BREAKOUT": {"active": True},
    "VOLUME_SPIKE": {"active": True},
    "EMA_CROSS": {"active": True},
    "MACD": {"active": True},
}

# =========================
# BINANCE API COM CACHE
# =========================
def get_binance_klines(symbol, interval="1m", limit=100):
    key = (symbol, interval)
    now = time.time()

    if key in kline_cache:
        data, ts = kline_cache[key]
        if now - ts < CACHE_TTL:
            return data

    try:
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            kline_cache[key] = (data, now)
            return data
    except Exception as e:
        logger.error(f"Erro Binance {symbol} {interval}: {e}")

    return None

# =========================
# INDICADORES
# =========================
def calculate_ema(prices, period):
    if len(prices) < period:
        return prices[-1]

    ema = sum(prices[:period]) / period
    multiplier = 2 / (period + 1)

    for p in prices[period:]:
        ema = (p - ema) * multiplier + ema

    return ema

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50

    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i - 1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_stochastic(prices, period=14):
    if len(prices) < period:
        return 50

    low = min(prices[-period:])
    high = max(prices[-period:])

    if high == low:
        return 50

    return (prices[-1] - low) / (high - low) * 100

def calculate_macd(prices):
    return calculate_ema(prices, 12) - calculate_ema(prices, 26)

def calculate_indicators(prices, volumes, symbol, tf):
    ind = {
        "price": prices[-1],
        "ema9": calculate_ema(prices, 9),
        "ema21": calculate_ema(prices, 21),
        "rsi": calculate_rsi(prices),
        "stoch": calculate_stochastic(prices),
        "recent_high": max(prices[-20:]),
        "recent_low": min(prices[-20:]),
        "volume": volumes[-1],
        "volume_avg": sum(volumes[-20:]) / 20,
        "prices": prices,
    }

    prev = indicator_history.get((symbol, tf))
    indicator_history[(symbol, tf)] = ind
    return ind, prev

# =========================
# ESTRATÉGIAS
# =========================
def apply_strategies(ind, prev):
    signals = []

    if STRATEGIES["RSI_EXTREME"]["active"]:
        if ind["rsi"] < 30:
            signals.append(("COMPRA", "RSI OVERSOLD", 1.2))
        elif ind["rsi"] > 70:
            signals.append(("VENDA", "RSI OVERBOUGHT", 1.2))

    if STRATEGIES["STOCH_FAST"]["active"]:
        if ind["stoch"] < 20:
            signals.append(("COMPRA", "STOCH OVERSOLD", 1.1))
        elif ind["stoch"] > 80:
            signals.append(("VENDA", "STOCH OVERBOUGHT", 1.1))

    if STRATEGIES["PRICE_BREAKOUT"]["active"]:
        if ind["price"] > ind["recent_high"]:
            signals.append(("COMPRA", "BREAKOUT ALTA", 1.4))
        elif ind["price"] < ind["recent_low"]:
            signals.append(("VENDA", "BREAKDOWN BAIXA", 1.4))

    if STRATEGIES["VOLUME_SPIKE"]["active"]:
        if ind["volume"] > ind["volume_avg"] * 3:
            if prev and ind["price"] > prev["price"]:
                direction = "COMPRA"
            else:
                direction = "VENDA"
            signals.append((direction, "VOLUME SPIKE", 1.3))

    if STRATEGIES["EMA_CROSS"]["active"] and prev:
        if ind["ema9"] > ind["ema21"] and prev["ema9"] <= prev["ema21"]:
            signals.append(("COMPRA", "EMA GOLDEN CROSS", 1.3))
        elif ind["ema9"] < ind["ema21"] and prev["ema9"] >= prev["ema21"]:
            signals.append(("VENDA", "EMA DEATH CROSS", 1.3))

    if STRATEGIES["MACD"]["active"] and prev:
        macd = calculate_macd(ind["prices"])
        prev_macd = calculate_macd(prev["prices"])
        if macd > 0 and prev_macd <= 0:
            signals.append(("COMPRA", "MACD BULLISH", 1.2))
        elif macd < 0 and prev_macd >= 0:
            signals.append(("VENDA", "MACD BEARISH", 1.2))

    return signals

# =========================
# ANÁLISE MULTI-TF
# =========================
def analyze_symbol(symbol):
    buy_score = sell_score = 0
    reasons = []
    price = None
    used_tfs = []

    for tf in TIMEFRAMES:
        klines = get_binance_klines(symbol, tf)
        if not klines:
            continue

        closes = [float(k[4]) for k in klines]
        volumes = [float(k[5]) for k in klines]

        ind, prev = calculate_indicators(closes, volumes, symbol, tf)
        price = ind["price"]

        signals = apply_strategies(ind, prev)
        if not signals:
            continue

        used_tfs.append(tf)
        for d, r, w in signals:
            reasons.append(f"{tf}: {r}")
            if d == "COMPRA":
                buy_score += w
            else:
                sell_score += w

    if len(used_tfs) < 2:
        return None

    direction = "COMPRA" if buy_score > sell_score else "VENDA"
    score = max(buy_score, sell_score)
    confidence = min(score / 6, 1)

    if confidence < 0.5:
        return None

    return {
        "symbol": symbol,
        "direction": direction,
        "price": price,
        "confidence": confidence,
        "score": score,
        "reasons": reasons[:3],
        "timeframes": used_tfs,
        "timestamp": datetime.now(),
    }

# =========================
# TELEGRAM
# =========================
def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg},
            timeout=10
        )
    except:
        pass

def send_signal(signal):
    emoji = "🚀" if signal["direction"] == "COMPRA" else "🔻"
    msg = (
        f"{emoji} {signal['direction']}\n"
        f"Par: {signal['symbol']}\n"
        f"Preço: {signal['price']:.4f}\n"
        f"Confiança: {signal['confidence']:.0%}\n"
        f"Razões:\n" + "\n".join(signal["reasons"])
    )
    send_telegram(msg)

# =========================
# LOOP PRINCIPAL
# =========================
def run_bot():
    logger.info("🤖 BOT INICIADO")
    while True:
        for symbol in PAIRS:
            signal = analyze_symbol(symbol)
            if signal:
                send_signal(signal)
                time.sleep(1)
        time.sleep(60)

# =========================
# MAIN
# =========================
def main():
    threading.Thread(target=run_bot, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)

if __name__ == "__main__":
    main()
