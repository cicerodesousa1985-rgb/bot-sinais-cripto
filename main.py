import os, time, threading, uuid, requests
from flask import Flask, jsonify, render_template_string
from collections import deque
from threading import Lock
from datetime import datetime

# ================= CONFIG =================
PORT = int(os.getenv("PORT", 10000))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

SYMBOLS = ["BTCUSDT", "ETHUSDT"]
PRICE_MAP = {
    "BTCUSDT": "bitcoin",
    "ETHUSDT": "ethereum"
}

# ================= PRICE =================
def get_price(symbol):
    coin = PRICE_MAP[symbol]
    r = requests.get(
        f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd",
        timeout=10
    ).json()
    return r[coin]["usd"]

# ================= WINRATE =================
class Winrate:
    def __init__(self):
        self.lock = Lock()
        self.signals = deque(maxlen=2000)
        self.equity = [0.0]

    def add(self, s):
        with self.lock:
            self.signals.append(s)

    def close(self, sid, result, profit):
        with self.lock:
            for s in self.signals:
                if s["id"] == sid and s["resultado"] is None:
                    s["resultado"] = result
                    s["profit"] = profit
                    self.equity.append(self.equity[-1] + profit)
                    break

    def stats(self):
        with self.lock:
            closed = [s for s in self.signals if s["resultado"]]
            wins = [s for s in closed if s["resultado"] == "WIN"]
            losses = [s for s in closed if s["resultado"] == "LOSS"]

            winrate = round(len(wins)/len(closed)*100,1) if closed else 0
            avg_win = sum(s["profit"] for s in wins)/len(wins) if wins else 0
            avg_loss = abs(sum(s["profit"] for s in losses)/len(losses)) if losses else 0
            expectancy = round((winrate/100)*avg_win - (1-winrate/100)*avg_loss,2)

            peak = self.equity[0]
            dd = 0
            for e in self.equity:
                peak = max(peak, e)
                dd = max(dd, peak - e)

            return {
                "winrate": winrate,
                "wins": len(wins),
                "losses": len(losses),
                "equity": round(self.equity[-1],2),
                "drawdown": round(dd,2),
                "expectancy": expectancy,
                "equity_curve": self.equity
            }

WR = Winrate()

# ================= SIGNAL =================
def generate_signal(symbol):
    price = get_price(symbol)
    signal = {
        "id": str(uuid.uuid4()),
        "symbol": symbol,
        "entry": price,
        "stop": price * 0.98,
        "targets": [price * 1.02, price * 1.04],
        "resultado": None,
        "profit": 0
    }
    WR.add(signal)
    if TELEGRAM_TOKEN:
        telegram(f"🚀 NOVO SINAL {symbol}\nEntrada: {price:.2f}")
    threading.Thread(target=monitor_signal, args=(signal,), daemon=True).start()

def monitor_signal(s):
    while s["resultado"] is None:
        price = get_price(s["symbol"])
        if price <= s["stop"]:
            WR.close(s["id"], "LOSS", -1)
            notify_close(s)
            return
        for t in s["targets"]:
            if price >= t:
                profit = (t/s["entry"]-1)*100
                WR.close(s["id"], "WIN", round(profit,2))
                notify_close(s)
                return
        time.sleep(20)

# ================= TELEGRAM =================
def telegram(msg):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": msg}
    )

def notify_close(s):
    st = WR.stats()
    if TELEGRAM_TOKEN:
        telegram(
            f"✅ FECHADO {s['symbol']} {s['resultado']}\n"
            f"Profit: {s['profit']}%\n"
            f"Winrate: {st['winrate']}%\n"
            f"Equity: {st['equity']}"
        )

# ================= WORKER =================
def worker():
    while True:
        for sym in SYMBOLS:
            generate_signal(sym)
            time.sleep(5)
        time.sleep(300)

threading.Thread(target=worker, daemon=True).start()

# ================= DASHBOARD =================
HTML = """
<!DOCTYPE html>
<html>
<head>
<title>FatPig Pro</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
body{background:#0b0b0b;color:white;font-family:Arial}
.card{background:#151515;padding:20px;border-radius:10px;margin:10px}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
</style>
</head>
<body>
<h1>📊 FATPIG PRO DASHBOARD</h1>
<div class="grid">
<div class="card">Winrate<br><b id="w"></b>%</div>
<div class="card">Equity<br><b id="e"></b></div>
<div class="card">Drawdown<br><b id="d"></b></div>
<div class="card">Expectancy<br><b id="x"></b></div>
</div>
<canvas id="chart"></canvas>

<script>
fetch('/api/stats').then(r=>r.json()).then(d=>{
document.getElementById('w').innerText=d.winrate
document.getElementById('e').innerText=d.equity
document.getElementById('d').innerText=d.drawdown
document.getElementById('x').innerText=d.expectancy
new Chart(document.getElementById('chart'),{
type:'line',
data:{labels:d.equity_curve.map((_,i)=>i+1),
datasets:[{label:'Equity',data:d.equity_curve,borderColor:'#00ff88'}]}
})
})
</script>
</body>
</html>
"""

# ================= FLASK =================
app = Flask(__name__)

@app.route("/")
def dash():
    return render_template_string(HTML)

@app.route("/api/stats")
def stats():
    return jsonify(WR.stats())

app.run("0.0.0.0", PORT)
