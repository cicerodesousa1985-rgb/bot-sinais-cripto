import os
import time
import threading
import requests
import sqlite3
from datetime import datetime
from flask import Flask, render_template_string, jsonify
import logging
import random

# =========================
# CONFIG
# =========================
PORT = int(os.getenv("PORT", 10000))
DB_FILE = "trades.db"

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT", "XRPUSDT", "ADAUSDT"]
SCORE_MIN = 3

# =========================
# APP
# =========================
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger()

# =========================
# DATABASE
# =========================
def db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    c = db().cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT,
            side TEXT,
            entry REAL,
            tp REAL,
            sl REAL,
            result TEXT,
            pnl REAL,
            score INTEGER,
            strategies TEXT,
            open_time TEXT,
            close_time TEXT
        )
    """)
    db().commit()

init_db()

# =========================
# MARKET DATA
# =========================
def price(pair):
    coin = pair.replace("USDT", "")
    r = requests.get(
        f"https://min-api.cryptocompare.com/data/pricemultifull?fsyms={coin}&tsyms=USDT",
        timeout=10
    ).json()
    data = r["RAW"][coin]["USDT"]
    return data["PRICE"], data["CHANGEPCT24HOUR"]

def fear_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/", timeout=10).json()
        v = int(r["data"][0]["value"])
        return v
    except:
        return 50

# =========================
# STRATEGIES (8)
# =========================
def strategies(price, change, fg):
    s = []
    if change > 2: s.append("Momentum")
    if change < -2: s.append("Reversão")
    if fg < 30: s.append("Medo")
    if fg > 70: s.append("Ganância")
    if abs(change) > 4: s.append("Volatilidade")
    if change > 0: s.append("Tendência Alta")
    if change < 0: s.append("Tendência Baixa")
    if random.random() > 0.5: s.append("Fluxo")

    return list(set(s))

# =========================
# BOT LOOP
# =========================
def bot_loop():
    while True:
        try:
            pair = random.choice(PAIRS)
            p, ch = price(pair)
            fg = fear_greed()
            used = strategies(p, ch, fg)
            score = len(used)

            log.info(f"{pair} | score {score} | {used}")

            if score < SCORE_MIN:
                time.sleep(60)
                continue

            side = "BUY" if ch >= 0 else "SELL"
            tp = p * (1.02 if side == "BUY" else 0.98)
            sl = p * (0.97 if side == "BUY" else 1.03)

            # Simula fechamento real por preço
            time.sleep(random.randint(60, 180))
            final_price, _ = price(pair)

            win = (final_price >= tp if side == "BUY" else final_price <= tp)
            result = "WIN" if win else "LOSS"
            pnl = round((tp - p) if win else (sl - p), 2)

            c = db().cursor()
            c.execute("""
                INSERT INTO trades
                (pair, side, entry, tp, sl, result, pnl, score, strategies, open_time, close_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pair, side, p, tp, sl, result, pnl, score,
                ", ".join(used),
                datetime.now().strftime("%H:%M:%S"),
                datetime.now().strftime("%H:%M:%S")
            ))
            db().commit()

        except Exception as e:
            log.error(e)

        time.sleep(random.randint(120, 300))

# =========================
# DASHBOARD
# =========================
@app.route("/")
def dashboard():
    c = db().cursor()
    trades = c.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 50").fetchall()

    wins = sum(1 for t in trades if t["result"] == "WIN")
    losses = sum(1 for t in trades if t["result"] == "LOSS")
    winrate = round((wins / max(1, wins + losses)) * 100, 2)
    pnl = round(sum(t["pnl"] for t in trades), 2)

    return render_template_string(TEMPLATE,
        trades=trades,
        wins=wins,
        losses=losses,
        winrate=winrate,
        pnl=pnl
    )

# =========================
# HTML
# =========================
TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<title>FAT PIG ULTIMATE</title>
<style>
body{background:#000;color:#eee;font-family:Arial}
h1{color:#f5a623}
table{width:100%;border-collapse:collapse}
th,td{padding:10px;border-bottom:1px solid #222;text-align:center}
.win{color:#00ff99}
.loss{color:#ff4d4d}
</style>
</head>
<body>
<h1>🐷 FAT PIG ULTIMATE</h1>
<p>Winrate: {{winrate}}% | PnL: {{pnl}}</p>

<table>
<tr>
<th>Par</th><th>Lado</th><th>Resultado</th><th>Lucro</th><th>Score</th><th>Estratégias</th><th>Hora</th>
</tr>
{% for t in trades %}
<tr>
<td>{{t.pair}}</td>
<td>{{t.side}}</td>
<td class="{{'win' if t.result=='WIN' else 'loss'}}">{{t.result}}</td>
<td>{{t.pnl}}</td>
<td>{{t.score}}</td>
<td>{{t.strategies}}</td>
<td>{{t.close_time}}</td>
</tr>
{% endfor %}
</table>
</body>
</html>
"""

# =========================
# START
# =========================
if __name__ == "__main__":
    threading.Thread(target=bot_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
