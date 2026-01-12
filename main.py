import os, time, threading, uuid, requests, math
from flask import Flask, jsonify, request, render_template_string
from collections import deque
from threading import Lock
from datetime import datetime

PORT = 10000

# ================= USERS / SUBSCRIPTIONS =================
USERS = {
    "demo": {"plan": "FREE", "limit": 3},
    "pro123": {"plan": "PRO", "limit": 999}
}

# ================= PRICE & CANDLES =================
def get_candles(symbol, limit=100):
    fsym = symbol.replace("USDT","")
    url = f"https://min-api.cryptocompare.com/data/v2/histominute?fsym={fsym}&tsym=USD&limit={limit}"
    return requests.get(url, timeout=10).json()["Data"]["Data"]

def get_price(symbol):
    return get_candles(symbol, 1)[-1]["close"]

# ================= INDICATORS =================
def ema(values, period):
    k = 2/(period+1)
    ema_val = values[0]
    for v in values:
        ema_val = v*k + ema_val*(1-k)
    return ema_val

def rsi(values, period=14):
    gains, losses = 0,0
    for i in range(1,period+1):
        diff = values[-i] - values[-i-1]
        if diff > 0: gains += diff
        else: losses -= diff
    if losses == 0: return 100
    rs = gains / losses
    return 100 - (100/(1+rs))

# ================= AI FILTER =================
def ai_score(prices):
    r = rsi(prices)
    e9 = ema(prices,9)
    e21 = ema(prices,21)
    score = 0
    if r < 30: score += 1
    if e9 > e21: score += 1
    return score >= 2  # only good signals pass

# ================= WINRATE SYSTEM =================
class Engine:
    def __init__(self):
        self.lock = Lock()
        self.data = {}
    def init_user(self, key):
        if key not in self.data:
            self.data[key] = {
                "signals": [],
                "equity":[0]
            }
    def add_signal(self, key, s):
        with self.lock:
            self.data[key]["signals"].append(s)
    def close(self, key, sid, res, profit):
        with self.lock:
            for s in self.data[key]["signals"]:
                if s["id"]==sid and s["res"] is None:
                    s["res"]=res
                    s["profit"]=profit
                    self.data[key]["equity"].append(self.data[key]["equity"][-1]+profit)
    def stats(self, key):
        sigs = self.data[key]["signals"]
        closed = [s for s in sigs if s["res"]]
        wins = [s for s in closed if s["res"]=="WIN"]
        losses = [s for s in closed if s["res"]=="LOSS"]
        wr = round(len(wins)/len(closed)*100,1) if closed else 0
        return {
            "winrate": wr,
            "wins":len(wins),
            "losses":len(losses),
            "equity": round(self.data[key]["equity"][-1],2),
            "curve": self.data[key]["equity"]
        }

ENGINE = Engine()
SYMBOLS = ["BTCUSDT","ETHUSDT"]

# ================= SIGNAL =================
def generate_signal(user, symbol):
    candles = get_candles(symbol)
    prices = [c["close"] for c in candles]
    if not ai_score(prices): return

    price = prices[-1]
    s = {
        "id":str(uuid.uuid4()),
        "symbol":symbol,
        "entry":price,
        "stop":price*0.98,
        "tp":price*1.02,
        "res":None,
        "profit":0
    }
    ENGINE.add_signal(user,s)
    threading.Thread(target=monitor,args=(user,s),daemon=True).start()

def monitor(user,s):
    while s["res"] is None:
        p = get_price(s["symbol"])
        if p <= s["stop"]:
            ENGINE.close(user,s["id"],"LOSS",-1)
            return
        if p >= s["tp"]:
            ENGINE.close(user,s["id"],"WIN",(p/s["entry"]-1)*100)
            return
        time.sleep(30)

# ================= WORKER =================
def worker():
    while True:
        for key in USERS:
            ENGINE.init_user(key)
            for sym in SYMBOLS:
                if USERS[key]["limit"]>0:
                    generate_signal(key,sym)
        time.sleep(300)

threading.Thread(target=worker,daemon=True).start()

# ================= DASHBOARD =================
HTML = """
<!doctype html><html><head>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>body{background:#0b0b0b;color:white;font-family:Arial}</style>
</head><body>
<h1>FAT PIG PRO</h1>
<div id="stats"></div>
<canvas id="c"></canvas>
<script>
fetch('/api/stats?key={{key}}').then(r=>r.json()).then(d=>{
document.getElementById('stats').innerHTML=
'Winrate:'+d.winrate+'% | Equity:'+d.equity
new Chart(document.getElementById('c'),{
type:'line',
data:{labels:d.curve.map((_,i)=>i+1),
datasets:[{data:d.curve,borderColor:'#00ff88'}]}
})
})
</script>
</body></html>
"""

# ================= FLASK =================
app = Flask(__name__)

@app.route("/")
def dash():
    key = request.args.get("key","demo")
    return render_template_string(HTML,key=key)

@app.route("/api/stats")
def stats():
    key = request.args.get("key","demo")
    ENGINE.init_user(key)
    return jsonify(ENGINE.stats(key))

app.run("0.0.0.0",PORT)
