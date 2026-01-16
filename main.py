from flask import Flask, render_template_string
import sqlite3
import threading
import time
import requests
import random
from datetime import datetime

app = Flask(__name__)
DB = "trades.db"

# =========================
# BANCO DE DADOS
# =========================
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            side TEXT,
            entry REAL,
            exit REAL,
            result TEXT,
            profit REAL,
            time TEXT
        )
    """)
    conn.commit()
    conn.close()

def add_trade(symbol, side, entry, exit_price):
    profit = (exit_price - entry) if side == "BUY" else (entry - exit_price)
    result = "WIN" if profit > 0 else "LOSS"

    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        INSERT INTO trades (symbol, side, entry, exit, result, profit, time)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        symbol, side, entry, exit_price,
        result, round(profit, 2),
        datetime.now().strftime("%d/%m %H:%M")
    ))
    conn.commit()
    conn.close()

def get_trades():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 50")
    rows = c.fetchall()
    conn.close()
    return rows

# =========================
# PREÇO REAL (CryptoCompare)
# =========================
def get_price(symbol):
    coin = symbol.replace("USDT", "")
    url = f"https://min-api.cryptocompare.com/data/price?fsym={coin}&tsyms=USDT"
    return requests.get(url, timeout=10).json()["USDT"]

# =========================
# BOT REAL DE SINAIS
# =========================
def bot_loop():
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT"]
    while True:
        try:
            symbol = random.choice(symbols)
            side = random.choice(["BUY", "SELL"])

            entry = get_price(symbol)

            # tempo real de trade
            time.sleep(20)

            exit_price = get_price(symbol)

            add_trade(symbol, side, entry, exit_price)

        except Exception as e:
            print("Erro no bot:", e)

        time.sleep(60)

# =========================
# DASHBOARD
# =========================
@app.route("/")
def dashboard():
    trades = get_trades()

    wins = len([t for t in trades if t[5] == "WIN"])
    losses = len([t for t in trades if t[5] == "LOSS"])
    total = wins + losses
    winrate = round((wins / total) * 100, 2) if total else 0
    pnl = round(sum(t[6] for t in trades), 2)

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>FAT PIG ULTIMATE</title>
        <style>
            body { background:#0b0b0b; color:#fff; font-family:Arial; padding:30px }
            h1 { margin-bottom:20px }
            .cards { display:grid; grid-template-columns:repeat(4,1fr); gap:15px }
            .card { background:#111; padding:20px; border-radius:14px; text-align:center }
            table { width:100%; margin-top:30px; border-collapse:collapse }
            th,td { padding:10px; border-bottom:1px solid #222; text-align:center }
            .win { color:#00ff9d }
            .loss { color:#ff4d4d }
        </style>
    </head>
    <body>
        <h1>🐷 FAT PIG ULTIMATE</h1>

        <div class="cards">
            <div class="card">Winrate<br><b>{{ winrate }}%</b></div>
            <div class="card">Wins<br><b>{{ wins }}</b></div>
            <div class="card">Losses<br><b>{{ losses }}</b></div>
            <div class="card">PnL<br><b>{{ pnl }}</b></div>
        </div>

        <table>
            <tr>
                <th>Par</th><th>Direção</th><th>Entrada</th><th>Saída</th>
                <th>Resultado</th><th>Lucro</th><th>Hora</th>
            </tr>
            {% for t in trades %}
            <tr>
                <td>{{ t[1] }}</td>
                <td>{{ t[2] }}</td>
                <td>{{ t[3] }}</td>
                <td>{{ t[4] }}</td>
                <td class="{{ 'win' if t[5]=='WIN' else 'loss' }}">{{ t[5] }}</td>
                <td>{{ t[6] }}</td>
                <td>{{ t[7] }}</td>
            </tr>
            {% endfor %}
        </table>
    </body>
    </html>
    """

    return render_template_string(
        html,
        trades=trades,
        wins=wins,
        losses=losses,
        winrate=winrate,
        pnl=pnl
    )

# =========================
# START
# =========================
if __name__ == "__main__":
    init_db()
    threading.Thread(target=bot_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
