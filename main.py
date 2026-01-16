import threading, time, sqlite3, requests, logging
from datetime import datetime
from flask import Flask, render_template_string

# ======================
# LOGS
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
TP = 0.02
SL = 0.03

# ======================
# DATABASE
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
            result TEXT,
            profit REAL,
            strategy TEXT,
            score INTEGER,
            sentiment TEXT,
            time TEXT
        )
    """)
    conn.commit()
    conn.close()

def add_trade(row):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        INSERT INTO trades
        (symbol, side, entry, exit, result, profit, strategy, score, sentiment, time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, row)
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
# APIs
# ======================
def get_price_change(symbol):
    coin = symbol.replace("USDT", "")
    url = f"https://min-api.cryptocompare.com/data/pricemultifull?fsyms={coin}&tsyms=USDT"
    raw = requests.get(url, timeout=10).json()["RAW"][coin]["USDT"]
    return raw["PRICE"], raw["CHANGEPCT24HOUR"]

def get_sentiment():
    try:
        s = requests.get("https://api.alternative.me/fng/", timeout=10).json()
        return s["data"][0]["value_classification"]
    except:
        return "Neutral"

# ======================
# 8 ESTRATÉGIAS
# ======================
def strategies(price, change, sentiment):
    score = 0
    used = []

    # 1 Tendência 24h
    if change > 3:
        score -= 1; used.append("Correção 24h")
    elif change < -3:
        score += 1; used.append("Repique 24h")

    # 2 Momentum curto
    if abs(change) > 1:
        score += 1 if change > 0 else -1
        used.append("Momentum")

    # 3 Breakout simples
    if abs(change) > 4:
        score += 1 if change > 0 else -1
        used.append("Breakout")

    # 4 Pullback
    if 0 < abs(change) < 2:
        score += 1 if change < 0 else -1
        used.append("Pullback")

    # 5 Reversão estatística
    if abs(change) > 6:
        score -= 1 if change > 0 else +1
        used.append("Reversão")

    # 6 Sentimento
    if sentiment in ["Extreme Fear", "Fear"]:
        score += 1; used.append("Medo")
    elif sentiment in ["Extreme Greed", "Greed"]:
        score -= 1; used.append("Ganância")

    # 7 Confirmação MTF (simples)
    if abs(change) > 2:
        score += 1 if change > 0 else -1
        used.append("MTF")

    # 8 Filtro volatilidade
    if abs(change) < 0.3:
        used.append("Sem Volatilidade")
        return None, 0, used

    side = "BUY" if score > 0 else "SELL"
    return side, score, used

# ======================
# BOT
# ======================
def bot_loop():
    log.info("Bot multi-estratégia iniciado")
    while True:
        try:
            for s in SYMBOLS:
                price, change = get_price_change(s)
                sentiment = get_sentiment()
                side, score, used = strategies(price, change, sentiment)

                if not side:
                    continue

                log.info(f"{s} | {side} | Score {score} | {used}")

                time.sleep(30)

                exit_price, _ = get_price_change(s)
                profit = (exit_price - price) if side == "BUY" else (price - exit_price)
                result = "WIN" if profit > 0 else "LOSS"

                add_trade((
                    s, side, round(price,2), round(exit_price,2),
                    result, round(profit,2),
                    ", ".join(used), score, sentiment,
                    datetime.now().strftime("%d/%m %H:%M")
                ))

                time.sleep(60)

        except Exception as e:
            log.error(e)
            time.sleep(60)

# ======================
# DASHBOARD
# ======================
@app.route("/")
def dash():
    t = get_trades()
    wins = len([x for x in t if x[5]=="WIN"])
    losses = len([x for x in t if x[5]=="LOSS"])
    total = wins+losses
    winrate = round((wins/total)*100,2) if total else 0
    pnl = round(sum(x[6] for x in t),2)

    html = """
    <html><head>
    <title>FAT PIG ULTIMATE</title>
    <style>
    body{background:#050505;color:#eee;font-family:Arial;padding:30px}
    table{width:100%;border-collapse:collapse;margin-top:30px}
    th,td{border-bottom:1px solid #222;padding:8px;text-align:center}
    .win{color:#00ff9d}.loss{color:#ff4d4d}
    </style></head><body>
    <h1>🐷 FAT PIG ULTIMATE</h1>
    <p>Winrate: {{w}}% | PnL: {{p}}</p>

    <table>
    <tr><th>Par</th><th>Lado</th><th>Resultado</th><th>Lucro</th><th>Score</th><th>Estratégias</th><th>Hora</th></tr>
    {% for x in t %}
    <tr>
    <td>{{x[1]}}</td>
    <td>{{x[2]}}</td>
    <td class="{{'win' if x[5]=='WIN' else 'loss'}}">{{x[5]}}</td>
    <td>{{x[6]}}</td>
    <td>{{x[8]}}</td>
    <td>{{x[7]}}</td>
    <td>{{x[10]}}</td>
    </tr>
    {% endfor %}
    </table>
    </body></html>
    """
    return render_template_string(html, t=t, w=winrate, p=pnl)

# ======================
# START
# ======================
if __name__ == "__main__":
    init_db()
    threading.Thread(target=bot_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
