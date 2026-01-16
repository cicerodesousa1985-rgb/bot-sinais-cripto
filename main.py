import threading
import time
import sqlite3
import requests
from datetime import datetime
from flask import Flask, render_template_string

# ======================
# CONFIG
# ======================
app = Flask(__name__)
DB = "trades.db"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT"]
TP_PERCENT = 0.02   # 2%
SL_PERCENT = 0.03   # 3%

# ======================
# BANCO DE DADOS
# ======================
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
            tp REAL,
            sl REAL,
            result TEXT,
            profit REAL,
            confidence INTEGER,
            sentiment TEXT,
            time TEXT
        )
    """)
    conn.commit()
    conn.close()

def add_trade(data):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        INSERT INTO trades
        (symbol, side, entry, exit, tp, sl, result, profit, confidence, sentiment, time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, data)
    conn.commit()
    conn.close()

def get_trades():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 50")
    rows = c.fetchall()
    conn.close()
    return rows

# ======================
# APIs REAIS
# ======================
def get_price_and_change(symbol):
    coin = symbol.replace("USDT", "")
    url = f"https://min-api.cryptocompare.com/data/pricemultifull?fsyms={coin}&tsyms=USDT"
    data = requests.get(url, timeout=10).json()
    raw = data["RAW"][coin]["USDT"]
    return raw["PRICE"], raw["CHANGEPCT24HOUR"]

def get_sentiment():
    try:
        res = requests.get("https://api.alternative.me/fng/", timeout=10).json()
        status = res["data"][0]["value_classification"]
        traduz = {
            "Greed": "GANÂNCIA",
            "Extreme Greed": "GANÂNCIA EXTREMA",
            "Fear": "MEDO",
            "Extreme Fear": "MEDO EXTREMO",
            "Neutral": "NEUTRO"
        }
        return traduz.get(status, "NEUTRO")
    except:
        return "NEUTRO"

# ======================
# ESTRATÉGIA ORIGINAL
# ======================
def decide_trade(change):
    if change > 3:
        return "SELL"
    elif change < -3:
        return "BUY"
    else:
        return "BUY" if change > 0 else "SELL"

# ======================
# BOT REAL
# ======================
def bot_loop():
    while True:
        try:
            for symbol in SYMBOLS:
                entry, change = get_price_and_change(symbol)
                side = decide_trade(change)
                sentiment = get_sentiment()
                confidence = min(99, max(92, int(abs(change) * 3 + 90)))

                if side == "BUY":
                    tp = entry * (1 + TP_PERCENT)
                    sl = entry * (1 - SL_PERCENT)
                else:
                    tp = entry * (1 - TP_PERCENT)
                    sl = entry * (1 + SL_PERCENT)

                # tempo real de trade
                time.sleep(30)
                exit_price, _ = get_price_and_change(symbol)

                profit = (exit_price - entry) if side == "BUY" else (entry - exit_price)
                result = "WIN" if profit > 0 else "LOSS"

                add_trade((
                    symbol,
                    side,
                    round(entry, 2),
                    round(exit_price, 2),
                    round(tp, 2),
                    round(sl, 2),
                    result,
                    round(profit, 2),
                    confidence,
                    sentiment,
                    datetime.now().strftime("%d/%m %H:%M")
                ))

                time.sleep(60)

        except Exception as e:
            print("Erro no bot:", e)
            time.sleep(60)

# ======================
# DASHBOARD PREMIUM
# ======================
@app.route("/")
def dashboard():
    trades = get_trades()

    wins = len([t for t in trades if t[7] == "WIN"])
    losses = len([t for t in trades if t[7] == "LOSS"])
    total = wins + losses
    winrate = round((wins / total) * 100, 2) if total else 0
    pnl = round(sum(t[8] for t in trades), 2)

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>FAT PIG ULTIMATE</title>
        <style>
            body { background:#050505; color:#f0f0f0; font-family:Arial; padding:30px }
            h1 { margin-bottom:20px }
            .cards { display:grid; grid-template-columns:repeat(5,1fr); gap:15px }
            .card { background:#111; padding:20px; border-radius:16px; text-align:center }
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
            <div class="card">Trades<br><b>{{ total }}</b></div>
        </div>

        <table>
            <tr>
                <th>Par</th><th>Lado</th><th>Entrada</th><th>Saída</th>
                <th>TP</th><th>SL</th><th>Resultado</th>
                <th>Lucro</th><th>Conf.</th><th>Sentimento</th><th>Hora</th>
            </tr>
            {% for t in trades %}
            <tr>
                <td>{{ t[1] }}</td>
                <td>{{ t[2] }}</td>
                <td>{{ t[3] }}</td>
                <td>{{ t[4] }}</td>
                <td>{{ t[5] }}</td>
                <td>{{ t[6] }}</td>
                <td class="{{ 'win' if t[7]=='WIN' else 'loss' }}">{{ t[7] }}</td>
                <td>{{ t[8] }}</td>
                <td>{{ t[9] }}%</td>
                <td>{{ t[10] }}</td>
                <td>{{ t[11] }}</td>
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
        pnl=pnl,
        total=total
    )

# ======================
# START
# ======================
if __name__ == "__main__":
    init_db()
    threading.Thread(target=bot_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
