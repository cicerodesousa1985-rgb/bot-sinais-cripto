import ccxt
import pandas as pd
import numpy as np
import time
import threading
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import EMAIndicator, MACD
from ta.volatility import BollingerBands
from flask import Flask, render_template_string
from datetime import datetime

# ================= CONFIG =================
PAIRS = [
"BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","XRP/USDT",
"ADA/USDT","AVAX/USDT","DOGE/USDT","MATIC/USDT",
"LINK/USDT","LTC/USDT","DOT/USDT"
]

TIMEFRAME = "5m"
LIMIT = 150
STRONG_THRESHOLD = 6
NORMAL_THRESHOLD = 3

exchange = ccxt.binance()

signals = {}

# ================= DATA =================
def get_data(pair):
    ohlc = exchange.fetch_ohlcv(pair, timeframe=TIMEFRAME, limit=LIMIT)
    df = pd.DataFrame(ohlc, columns=["time","open","high","low","close","volume"])
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    return df

# ================= STRATEGIES =================
def strategy_ema_cross(df):
    ema9 = EMAIndicator(df["close"], 9).ema_indicator()
    ema21 = EMAIndicator(df["close"], 21).ema_indicator()
    if ema9.iloc[-1] > ema21.iloc[-1]:
        return ("buy",1)
    elif ema9.iloc[-1] < ema21.iloc[-1]:
        return ("sell",1)
    return ("neutral",0)

def strategy_rsi(df):
    rsi = RSIIndicator(df["close"],14).rsi()
    if rsi.iloc[-1] < 30:
        return ("buy",1)
    elif rsi.iloc[-1] > 70:
        return ("sell",1)
    return ("neutral",0)

def strategy_macd(df):
    macd = MACD(df["close"])
    if macd.macd_diff().iloc[-1] > 0:
        return ("buy",1)
    elif macd.macd_diff().iloc[-1] < 0:
        return ("sell",1)
    return ("neutral",0)

def strategy_bb(df):
    bb = BollingerBands(df["close"],20)
    if df["close"].iloc[-1] < bb.bollinger_lband().iloc[-1]:
        return ("buy",1)
    elif df["close"].iloc[-1] > bb.bollinger_hband().iloc[-1]:
        return ("sell",1)
    return ("neutral",0)

def strategy_volume(df):
    vol_mean = df["volume"].rolling(20).mean().iloc[-1]
    if df["volume"].iloc[-1] > vol_mean*1.5:
        if df["close"].iloc[-1] > df["open"].iloc[-1]:
            return ("buy",1)
        else:
            return ("sell",1)
    return ("neutral",0)

def strategy_breakout(df):
    high = df["high"].rolling(20).max().iloc[-2]
    low = df["low"].rolling(20).min().iloc[-2]
    if df["close"].iloc[-1] > high:
        return ("buy",1)
    elif df["close"].iloc[-1] < low:
        return ("sell",1)
    return ("neutral",0)

def strategy_ema200(df):
    ema200 = EMAIndicator(df["close"],200).ema_indicator()
    if df["close"].iloc[-1] > ema200.iloc[-1]:
        return ("buy",1)
    else:
        return ("sell",1)

def strategy_stoch(df):
    st = StochasticOscillator(df["high"],df["low"],df["close"])
    if st.stoch().iloc[-1] < 20:
        return ("buy",1)
    elif st.stoch().iloc[-1] > 80:
        return ("sell",1)
    return ("neutral",0)

# ================= SCORE =================
def analyze(pair):
    df = get_data(pair)

    strategies = [
        strategy_ema_cross,
        strategy_rsi,
        strategy_macd,
        strategy_bb,
        strategy_volume,
        strategy_breakout,
        strategy_ema200,
        strategy_stoch
    ]

    results = []
    score = 0
    for strat in strategies:
        s,w = strat(df)
        results.append((strat.__name__,s))
        if s != "neutral":
            score += w if s=="buy" else -w

    if score >= STRONG_THRESHOLD:
        final = "STRONG BUY"
    elif score >= NORMAL_THRESHOLD:
        final = "BUY"
    elif score <= -STRONG_THRESHOLD:
        final = "STRONG SELL"
    elif score <= -NORMAL_THRESHOLD:
        final = "SELL"
    else:
        final = "NEUTRAL"

    signals[pair] = {
        "pair": pair,
        "signal": final,
        "score": score,
        "details": results,
        "time": datetime.now().strftime("%H:%M:%S")
    }

# ================= LOOP =================
def bot_loop():
    while True:
        for pair in PAIRS:
            try:
                analyze(pair)
            except Exception as e:
                print(pair, e)
        time.sleep(20)

# ================= DASH =================
app = Flask(__name__)

TEMPLATE = """
<html>
<head>
<meta http-equiv="refresh" content="10">
<style>
body{background:#050505;color:white;font-family:Arial}
.buy{color:#00ff99}
.sell{color:#ff4d4d}
.neutral{color:#ffaa00}
table{width:100%;border-collapse:collapse}
td,th{padding:10px;border-bottom:1px solid #222;text-align:center}
</style>
</head>
<body>
<h2>🐷 FAT PIG QUANT SIGNALS</h2>
<table>
<tr><th>Par</th><th>Sinal</th><th>Score</th><th>Hora</th><th>Estratégias</th></tr>
{% for s in signals.values() %}
<tr>
<td>{{s.pair}}</td>
<td class="{{ 'buy' if 'BUY' in s.signal else 'sell' if 'SELL' in s.signal else 'neutral' }}">{{s.signal}}</td>
<td>{{s.score}}</td>
<td>{{s.time}}</td>
<td>
{% for d in s.details %}
{{d[0]}}={{d[1]}} |
{% endfor %}
</td>
</tr>
{% endfor %}
</table>
</body>
</html>
"""

@app.route("/")
def dash():
    return render_template_string(TEMPLATE, signals=signals)

# ================= START =================
if __name__ == "__main__":
    threading.Thread(target=bot_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
