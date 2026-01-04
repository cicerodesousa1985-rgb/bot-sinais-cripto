import os
import time
import threading
import requests
import logging
import random
from datetime import datetime, timedelta
from flask import Flask, render_template_string, jsonify

# =========================
# CONFIGURAÇÃO
# =========================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

signals_paused = False
last_signals = []
bot_start_time = datetime.now()

# =========================
# CACHE & HISTÓRICO
# =========================
indicator_history = {}     # (symbol, timeframe)
kline_cache = {}           # (symbol, timeframe)
CACHE_TTL = 30             # segundos

# =========================
# CONFIGURAÇÃO EXPANDIDA
# =========================
TIMEFRAMES = ['1m', '5m', '15m']

PAIRS = [
    'BTCUSDT','ETHUSDT','BNBUSDT','SOLUSDT','XRPUSDT','ADAUSDT','AVAXUSDT',
    'DOGEUSDT','DOTUSDT','TRXUSDT','LINKUSDT','MATICUSDT','LTCUSDT',
    'UNIUSDT','ATOMUSDT','ETCUSDT','XLMUSDT','FILUSDT','NEARUSDT'
]

STRATEGIES = {
    'RSI_EXTREME': {'weight': 1.4, 'active': True},
    'STOCH_FAST': {'weight': 1.2, 'active': True},
    'PRICE_BREAKOUT': {'weight': 1.4, 'active': True},
    'VOLUME_SPIKE': {'weight': 1.3, 'active': True},
    'EMA_CROSS': {'weight': 1.3, 'active': True},
    'MACD': {'weight': 1.2, 'active': True},
}

# =========================
# BINANCE COM CACHE
# =========================
def get_binance_klines(symbol, interval='1m', limit=100):
    key = (symbol, interval)
    now = time.time()

    if key in kline_cache:
        data, ts = kline_cache[key]
        if now - ts < CACHE_TTL:
            return data

    try:
        url = "https://api.binance.com/api/v3/klines"
        r = requests.get(url, params={
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }, timeout=10)

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

    sma = sum(prices[:period]) / period
    ema = sma
    mult = 2 / (period + 1)

    for p in prices[period:]:
        ema = (p - ema) * mult + ema

    return ema

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50

    gains, losses = [], []
    for i in range(1, len(prices)):
        delta = prices[i] - prices[i-1]
        gains.append(max(delta, 0))
        losses.append(abs(min(delta, 0)))

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
    ema12 = calculate_ema(prices, 12)
    ema26 = calculate_ema(prices, 26)
    return ema12 - ema26

def calculate_indicators(prices, volumes, symbol, tf):
    indicators = {
        'price': prices[-1],
        'ema9': calculate_ema(prices, 9),
        'ema21': calculate_ema(prices, 21),
        'rsi': calculate_rsi(prices),
        'stoch': calculate_stochastic(prices),
        'recent_high': max(prices[-20:]),
        'recent_low': min(prices[-20:]),
        'volume_avg': sum(volumes[-20:]) / 20,
        'volume': volumes[-1],
        'prices': prices
    }

    prev = indicator_history.get((symbol, tf))
    indicator_history[(symbol, tf)] = indicators
    return indicators, prev

# =========================
# ESTRATÉGIAS
# =========================
def apply_strategies(ind, prev):
    signals = []

    if STRATEGIES['RSI_EXTREME']['active']:
        if ind['rsi'] < 30:
            signals.append(('COMPRA', 'RSI OVERSOLD', 1.2))
        elif ind['rsi'] > 70:
            signals.append(('VENDA', 'RSI OVERBOUGHT', 1.2))

    if STRATEGIES['STOCH_FAST']['active']:
        if ind['stoch'] < 20:
            signals.append(('COMPRA', 'STOCH OVERSOLD', 1.1))
        elif ind['stoch'] > 80:
            signals.append(('VENDA', 'STOCH OVERBOUGHT', 1.1))

    if STRATEGIES['PRICE_BREAKOUT']['active']:
        if ind['price'] > ind['recent_high']:
            signals.append(('COMPRA', 'BREAKOUT ALTA', 1.4))
        elif ind['price'] < ind['recent_low']:
            signals.append(('VENDA', 'BREAKDOWN BAIXA', 1.4))

    if STRATEGIES['VOLUME_SPIKE']['active']:
        if ind['volume'] > ind['volume_avg'] * 3:
            direction = 'COMPRA' if ind['price'] > prev['price'] if prev else True else 'VENDA'
            signals.append((direction, 'VOLUME SPIKE', 1.3))

    if STRATEGIES['EMA_CROSS']['active'] and prev:
        if ind['ema9'] > ind['ema21'] and prev['ema9'] <= prev['ema21']:
            signals.append(('COMPRA', 'EMA GOLDEN CROSS', 1.3))
        elif ind['ema9'] < ind['ema21'] and prev['ema9'] >= prev['ema21']:
            signals.append(('VENDA', 'EMA DEATH CROSS', 1.3))

    if STRATEGIES['MACD']['active'] and prev:
        macd = calculate_macd(ind['prices'])
        prev_macd = calculate_macd(prev['prices'])
        if macd > 0 and prev_macd <= 0:
            signals.append(('COMPRA', 'MACD BULLISH', 1.2))
        elif macd < 0 and prev_macd >= 0:
            signals.append(('VENDA', 'MACD BEARISH', 1.2))

    return signals

# =========================
# MULTI TIMEFRAME REAL
# =========================
def analyze_symbol(symbol):
    buy_score = sell_score = 0
    reasons = []
    price = None
    tfs = []

    for tf in TIMEFRAMES:
        klines = get_binance_klines(symbol, tf)
        if not klines:
            continue

        closes = [float(k[4]) for k in klines]
        volumes = [float(k[5]) for k in klines]

        ind, prev = calculate_indicators(closes, volumes, symbol, tf)
        price = ind['price']

        signals = apply_strategies(ind, prev)
        if not signals:
            continue

        tfs.append(tf)
        for d, r, w in signals:
            reasons.append(f"{tf}: {r}")
            if d == 'COMPRA':
                buy_score += w
            else:
                sell_score += w

    if len(tfs) < 2:
        return None

    direction = 'COMPRA' if buy_score > sell_score else 'VENDA'
    score = max(buy_score, sell_score)
    confidence = min(score / 6, 1)

    if confidence < 0.5:
        return None

    return {
        'symbol': symbol,
        'direction': direction,
        'price': price,
        'score': score,
        'confidence': confidence,
        'reasons': reasons[:3],
        'timeframes': tfs,
        'timestamp': datetime.now()
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
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except:
        pass

def send_signal(signal):
    emoji = "🚀" if signal['direction'] == 'COMPRA' else "🔻"
    msg = (
        f"{emoji} <b>{signal['direction']}</b>\n"
        f"Par: <code>{signal['symbol']}</code>\n"
        f"Preço: {signal['price']:.4f}\n"
        f"Confiança: {signal['confidence']:.0%}\n"
        f"Score: {signal['score']:.1f}\n"
        f"Razões:\n" + "\n".join(signal['reasons'])
    )
    send_telegram(msg)
    last_signals.append(signal)
    last_signals[:] = last_signals[-100:]

# =========================
# LOOP PRINCIPAL
# =========================
def run_bot():
    logger.info("🤖 BOT INICIADO")
    while True:
        if not signals_paused:
            for s in PAIRS:
                signal = analyze_symbol(s)
                if signal:
                    send_signal(signal)
                    time.sleep(1)
        time.sleep(60)

# =========================
# MAIN
# =========================
def main():
    threading.Thread(target=run_bot, daemon=True).start()
    app.run(host='0.0.0.0', port=10000)

if __name__ == "__main__":
    main()
