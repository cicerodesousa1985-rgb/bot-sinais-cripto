import os
import time
import threading
import requests
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from flask import Flask, render_template_string
import logging
from collections import deque

# =========================
# CONFIG
# =========================
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
PORT = int(os.getenv("PORT", "10000"))
DB_FILE = "historico_cripto_v3.json"

# =========================
# BANCO
# =========================
def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return {"sinais": [], "resultados": []}

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=2)

# =========================
# INDICADORES
# =========================
def calcular_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# =========================
# BOT
# =========================
class BotCriptoPro:
    def __init__(self):
        db = load_db()
        self.sinais = deque(db["sinais"], maxlen=50)
        self.resultados = db["resultados"]
        self.simbolos = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT"]

    def fetch_candles(self, symbol):
        coin = symbol.replace("USDT", "")
        url = f"https://min-api.cryptocompare.com/data/v2/histominute?fsym={coin}&tsym=USDT&limit=200"
        r = requests.get(url, timeout=10).json()
        df = pd.DataFrame(r["Data"]["Data"])
        return df

    def gerar_sinal(self):
        for symbol in self.simbolos:
            df = self.fetch_candles(symbol)
            close = df["close"]

            df["ema50"] = close.ewm(span=50).mean()
            df["ema200"] = close.ewm(span=200).mean()
            df["rsi"] = calcular_rsi(close)

            last = df.iloc[-1]
            price = last["close"]

            direcao = None

            if last["ema50"] > last["ema200"] and last["rsi"] < 35:
                direcao = "COMPRA"
                tp = price * 1.02
                sl = price * 0.97

            elif last["ema50"] < last["ema200"] and last["rsi"] > 65:
                direcao = "VENDA"
                tp = price * 0.98
                sl = price * 1.03

            if not direcao:
                continue

            sinal = {
                "id": int(time.time()),
                "par": symbol,
                "direcao": direcao,
                "entrada": price,
                "tp": tp,
                "sl": sl,
                "hora": datetime.now().isoformat(),
                "status": "ABERTO"
            }

            self.sinais.append(sinal)
            self.resultados.append(sinal)
            save_db({"sinais": list(self.sinais), "resultados": self.resultados})
            self.enviar_telegram(sinal)
            break  # apenas 1 sinal por ciclo

    def verificar_resultados(self):
        for s in self.resultados:
            if s["status"] != "ABERTO":
                continue

            if datetime.fromisoformat(s["hora"]) + timedelta(minutes=15) > datetime.now():
                continue

            coin = s["par"].replace("USDT", "")
            price = requests.get(
                f"https://min-api.cryptocompare.com/data/price?fsym={coin}&tsyms=USDT"
            ).json()["USDT"]

            if s["direcao"] == "COMPRA":
                s["status"] = "WIN" if price >= s["tp"] else "LOSS"
            else:
                s["status"] = "WIN" if price <= s["tp"] else "LOSS"

            save_db({"sinais": list(self.sinais), "resultados": self.resultados})

    def stats(self):
        closed = [r for r in self.resultados if r["status"] in ["WIN", "LOSS"]]
        if not closed:
            return {"winrate": 0, "total": 0}

        wins = len([r for r in closed if r["status"] == "WIN"])
        return {
            "winrate": round(wins / len(closed) * 100, 2),
            "total": len(closed)
        }

    def enviar_telegram(self, s):
        if not TELEGRAM_TOKEN:
            return
        msg = (
            f"🚨 *NOVO SINAL*\n\n"
            f"Par: *{s['par']}*\n"
            f"Direção: *{s['direcao']}*\n"
            f"Entrada: {s['entrada']:.2f}\n"
            f"TP: {s['tp']:.2f}\n"
            f"SL: {s['sl']:.2f}"
        )
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}
        )

bot = BotCriptoPro()

def loop():
    while True:
        bot.gerar_sinal()
        bot.verificar_resultados()
        time.sleep(600)

# =========================
# FLASK
# =========================
@app.route("/")
def index():
    stats = bot.stats()
    return render_template_string(
        "<h1>Winrate: {{s.winrate}}% | Total: {{s.total}}</h1>",
        s=stats
    )

if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    app.run("0.0.0.0", PORT)
