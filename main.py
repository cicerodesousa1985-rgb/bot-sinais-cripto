import ccxt
import pandas as pd
import time
import threading
from flask import Flask, render_template_string
from datetime import datetime

# ================= CONFIG =================
PARES = [
"BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","XRP/USDT",
"ADA/USDT","AVAX/USDT","DOGE/USDT","MATIC/USDT","LINK/USDT",
"LTC/USDT","DOT/USDT"
]

exchange = ccxt.binance()
timeframe = "5m"
limit = 120

signals_memory = {}

# ================= INDICADORES =================
def indicadores(df):
    df["ema9"] = df.close.ewm(span=9).mean()
    df["ema21"] = df.close.ewm(span=21).mean()
    df["ema200"] = df.close.ewm(span=200).mean()

    delta = df.close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    df["bb_mid"] = df.close.rolling(20).mean()
    df["bb_std"] = df.close.rolling(20).std()
    df["bb_up"] = df.bb_mid + 2*df.bb_std
    df["bb_low"] = df.bb_mid - 2*df.bb_std

    low14 = df.low.rolling(14).min()
    high14 = df.high.rolling(14).max()
    df["stoch"] = 100*(df.close-low14)/(high14-low14)

    return df

# ================= ESTRATÉGIAS =================
def estrategia_ema(df):
    if df.ema9.iloc[-1] > df.ema21.iloc[-1]: return "BUY",2
    if df.ema9.iloc[-1] < df.ema21.iloc[-1]: return "SELL",2
    return "NEUTRAL",0

def estrategia_rsi(df):
    r = df.rsi.iloc[-1]
    if r < 30: return "BUY",2
    if r > 70: return "SELL",2
    return "NEUTRAL",0

def estrategia_bb(df):
    c = df.close.iloc[-1]
    if c < df.bb_low.iloc[-1]: return "BUY",2
    if c > df.bb_up.iloc[-1]: return "SELL",2
    return "NEUTRAL",0

def estrategia_volume(df):
    if df.volume.iloc[-1] > df.volume.iloc[-20:-1].mean()*1.8:
        if df.close.iloc[-1] > df.open.iloc[-1]: return "BUY",1
        else: return "SELL",1
    return "NEUTRAL",0

def estrategia_trend(df):
    if df.close.iloc[-1] > df.ema200.iloc[-1]: return "BUY",1
    else: return "SELL",1

def estrategia_breakout(df):
    r = df.high.iloc[-20:-1].max()
    s = df.low.iloc[-20:-1].min()
    if df.close.iloc[-1] > r: return "BUY",2
    if df.close.iloc[-1] < s: return "SELL",2
    return "NEUTRAL",0

def estrategia_stoch(df):
    v = df.stoch.iloc[-1]
    if v < 20: return "BUY",1
    if v > 80: return "SELL",1
    return "NEUTRAL",0

def estrategia_macd(df):
    ema12 = df.close.ewm(span=12).mean()
    ema26 = df.close.ewm(span=26).mean()
    macd = ema12-ema26
    signal = macd.ewm(span=9).mean()
    if macd.iloc[-1] > signal.iloc[-1]: return "BUY",2
    else: return "SELL",2

estrategias = [
("EMA Cross",estrategia_ema),
("RSI",estrategia_rsi),
("Bollinger",estrategia_bb),
("Volume Spike",estrategia_volume),
("Trend EMA200",estrategia_trend),
("Breakout",estrategia_breakout),
("Stochastic",estrategia_stoch),
("MACD",estrategia_macd)
]

# ================= SCORE =================
def calcular_score(resultados):
    buy = sum(p for s,p,_ in resultados if s=="BUY")
    sell = sum(p for s,p,_ in resultados if s=="SELL")
    total = buy - sell
    if total >=6: return "STRONG BUY",total
    if total >=3: return "BUY",total
    if total <=-6: return "STRONG SELL",total
    if total <=-3: return "SELL",total
    return "NEUTRAL",total

# ================= ANALISE =================
def analyze(par):
    ohlcv = exchange.fetch_ohlcv(par,timeframe,limit=limit)
    df = pd.DataFrame(ohlcv,columns=["time","open","high","low","close","volume"])
    df = indicadores(df)

    resultados=[]
    usadas=[]
    for nome,func in estrategias:
        s,p = func(df)
        resultados.append((s,p,nome))
        if s!="NEUTRAL": usadas.append(nome)

    final,score = calcular_score(resultados)

    signals_memory[par]={
        "signal":final,
        "score":score,
        "details":usadas,
        "time":datetime.now().strftime("%H:%M:%S")
    }

# ================= LOOP =================
def bot_loop():
    while True:
        for par in PARES:
            try: analyze(par)
            except Exception as e: print(par,e)
        time.sleep(15)

# ================= DASH =================
@app.route("/")
def dashboard():
    global signals_memory

    signals = list(signals_memory.values())

    return render_template_string("""
<!DOCTYPE html>
<html lang="pt-br">
<head>
<meta charset="UTF-8">
<title>Fat Pig Quant Signals</title>
<meta http-equiv="refresh" content="20">

<style>
body{
    margin:0;
    background:#0b0b0b;
    font-family:'Segoe UI',sans-serif;
    color:white;
}

header{
    background:#000;
    padding:20px;
    text-align:center;
    border-bottom:1px solid #222;
}

header h1{margin:0;font-size:28px;}
header p{margin:5px 0 0;color:#888;}
.live{color:#00ff88;font-size:12px;}

.container{padding:20px 30px;}

table{
    width:100%;
    border-collapse:collapse;
    background:#111;
}

th{
    text-align:left;
    padding:14px;
    font-size:12px;
    color:#777;
    border-bottom:1px solid #222;
}

td{
    padding:14px;
    border-bottom:1px solid #181818;
    font-size:13px;
}

tr:hover{background:#161616;}

.badge{
    padding:6px 10px;
    border-radius:4px;
    font-weight:bold;
    font-size:12px;
}

.buy{background:#003d2a;color:#00ff88;}
.sell{background:#3a0000;color:#ff3b3b;}
.neutral{background:#3a3300;color:#ffd000;}

.scorebar{height:6px;background:#222;border-radius:3px;margin-top:6px;}
.fill{height:6px;border-radius:3px;background:#00ff88;}

.strategy{color:#00ccff;font-size:12px;}
.time{color:#aaa;font-size:12px;}
</style>
</head>

<body>

<header>
<h1>🐷 FAT PIG QUANT SIGNALS</h1>
<p>Real Time Crypto Signals</p>
<div class="live">● LIVE MARKET DATA</div>
</header>

<div class="container">
<table>
<thead>
<tr>
<th>PAR</th>
<th>SINAL</th>
<th>SCORE</th>
<th>ESTRATÉGIAS ATIVAS</th>
<th>DIREÇÃO</th>
<th>HORÁRIO</th>
</tr>
</thead>
<tbody>

{% for s in signals %}
<tr>
<td><b>{{s.pair}}</b></td>

<td>
<span class="badge 
{% if 'BUY' in s.signal %}buy
{% elif 'SELL' in s.signal %}sell
{% else %}neutral{% endif %}">
{{s.signal}}
</span>
</td>

<td>
{{s.score}}
<div class="scorebar">
<div class="fill" style="width: {{s.score}}%"></div>
</div>
</td>

<td class="strategy">{{s.strategies}}</td>

<td>
{% if 'BUY' in s.signal %}
<span style="color:#00ff88;">Bullish</span>
{% elif 'SELL' in s.signal %}
<span style="color:#ff3b3b;">Bearish</span>
{% else %}
<span style="color:#ffd000;">Sideways</span>
{% endif %}
</td>

<td class="time">{{s.time}}</td>
</tr>
{% endfor %}

</tbody>
</table>
</div>

</body>
</html>
""", signals=signals)
# ================= RUN =================
if __name__ == "__main__":
    threading.Thread(target=bot_loop,daemon=True).start()
    app.run(host="0.0.0.0",port=10000)
