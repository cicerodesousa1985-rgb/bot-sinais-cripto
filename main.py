import threading
import time
import sqlite3
import requests
import logging
from datetime import datetime
from flask import Flask, render_template_string

# ======================
# LOGGING PROFISSIONAL
# ======================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%d/%m %H:%M:%S"
)
log = logging.getLogger("FATPIG")

# ======================
# CONFIG
# ======================
app = Flask(__name__)
DB = "trades.db"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT"]
TP_PERCENT = 0.02
SL_PERCENT = 0.03

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
    log.info("Banco de dados inicializado")

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
    log.info(f"Trade salvo | {data[0]} | {data[1]} | {data[6]} | PnL: {data[7]}")

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
    raw = requests.get(url, timeout=10).json()["RAW"][coin]["USDT"]
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
    log.info("Bot iniciado")
    while True:
        try:
            for symbol in SYMBOLS:
                entry, change = get_price_and_change(symbol)
                side = decide_trade(change)
                sentiment = get_sentiment()
                confidence = min(99, max(92, int(abs(change) * 3 + 90)))

                tp = entry * (1 + TP_PERCENT if side == "BUY" else 1 - TP_PERCENT)
                sl = entry * (1 - SL_PERCENT if side == "BUY" else 1 + SL_PERCENT)

                log.info(f"SINAL | {symbol} | {side} | Entrada: {entry:.2f}")

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
            log.error(f"Erro no bot: {e}")
            time.sleep(60)

# ======================
# DASHBOARD COM GRÁFICOS
# ======================
@app.route("/")
def dashboard():
    trades = get_trades()
    wins = [t for t in trades if t[7] == "WIN"]
    losses = [t for t in trades if t[7] == "LOSS"]
    pnl = [t[8] for t in trades]

    html = """
<!DOCTYPE html>
<html>
<head>
<title>FAT PIG ULTIMATE</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
body{background:#050505;color:#f0f0f0;font-family:Arial;padding:30px}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:15px}
.card{background:#111;padding:20px;border-radius:16px;text-align:center}
canvas{margin-top:30px}
</style>
</head>
<body>

<h1>🐷 FAT PIG ULTIMATE</h1>

<div class="cards">
<div class="card">Winrate<br><b>{{ winrate }}%</b></div>
<div class="card">Wins<br><b>{{ wins }}</b></div>
<div class="card">Losses<br><b>{{ losses }}</b></div>
<div class="card">PnL<br><b>{{ pnl_total }}</b></div>
</div>

<canvas id="pnlChart"></canvas>

<script>
const pnlData = {{ pnl|safe }};
new Chart(document.getElementById("pnlChart"),{
type:"line",
data:{
labels:pnlData.map((_,i)=>i+1),
datasets:[{
label:"Equity Curve",
data:pnlData.reduce((a,x)=>{a.push((a.at(-1)||0)+x);return a},[]),
borderWidth:3,
tension:.4
}]
}
});
</script>

</body>
</html>
"""
    total = len(trades)
    winrate = round((len(wins)/total)*100,2) if total else 0

    return render_template_string(
        html,
        wins=len(wins),
        losses=len(losses),
        winrate=winrate,
        pnl_total=round(sum(pnl),2),
        pnl=pnl
    )

# ======================
# START
# ======================
if __name__ == "__main__":
    init_db()
    threading.Thread(target=bot_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
