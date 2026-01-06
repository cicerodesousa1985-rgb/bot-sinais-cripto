import os
import time
import threading
import requests
import json
from datetime import datetime
from flask import Flask, jsonify, render_template_string
import logging
from collections import deque
import random
from threading import Lock

# =========================
# CONFIGURAÇÕES GERAIS
# =========================
app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
BOT_INTERVAL = int(os.getenv("BOT_INTERVAL", "300"))
PORT = int(os.getenv("PORT", "10000"))

# MODOS
MODO_SIMULACAO = True
WINRATE_SIMULADO = 0.7
CACHE_PRECO_SEGUNDOS = 60

# =========================
# LOG
# =========================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# =========================
# CACHE DE PREÇOS
# =========================
precos_cache = {}

def buscar_preco_real(simbolo):
    agora = time.time()

    if simbolo in precos_cache:
        preco, timestamp = precos_cache[simbolo]
        if agora - timestamp < CACHE_PRECO_SEGUNDOS:
            return preco

    try:
        mapa = {
            "BTCUSDT": "bitcoin",
            "ETHUSDT": "ethereum",
            "BNBUSDT": "binancecoin",
            "SOLUSDT": "solana",
            "XRPUSDT": "ripple",
            "ADAUSDT": "cardano",
            "DOGEUSDT": "dogecoin"
        }

        coin = mapa.get(simbolo)
        if coin:
            r = requests.get(
                f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd",
                timeout=10
            )
            if r.status_code == 200:
                preco = r.json()[coin]["usd"]
                precos_cache[simbolo] = (preco, agora)
                return preco
    except:
        pass

    fallback = {
        "BTCUSDT": 43000,
        "ETHUSDT": 2300,
        "BNBUSDT": 315,
        "SOLUSDT": 100
    }
    return fallback.get(simbolo, 100)

# =========================
# SISTEMA DE WINRATE (THREAD SAFE)
# =========================
class SistemaWinrate:
    def __init__(self):
        self.lock = Lock()
        self.sinais = deque(maxlen=100)
        self.stats = {
            "total": 0,
            "wins": 0,
            "loss": 0,
            "profit": 0.0
        }

    def adicionar(self, sinal):
        with self.lock:
            self.sinais.append(sinal)
            self.stats["total"] += 1

    def fechar(self, sinal_id, resultado, profit):
        with self.lock:
            for s in self.sinais:
                if s["id"] == sinal_id:
                    s["resultado"] = resultado
                    s["profit"] = profit
                    if resultado == "WIN":
                        self.stats["wins"] += 1
                        self.stats["profit"] += profit
                    else:
                        self.stats["loss"] += 1
                        self.stats["profit"] -= abs(profit)
                    break

    def get_stats(self):
        with self.lock:
            total_fechado = self.stats["wins"] + self.stats["loss"]
            winrate = (self.stats["wins"] / total_fechado * 100) if total_fechado else 0
            return {
                "total_sinais": self.stats["total"],
                "wins": self.stats["wins"],
                "loss": self.stats["loss"],
                "winrate": winrate,
                "winrate_formatado": f"{winrate:.1f}%",
                "profit_total": self.stats["profit"],
                "profit_total_formatado": f"{self.stats['profit']:+.2f}"
            }

    def historico(self, n=20):
        with self.lock:
            return list(self.sinais)[-n:]

sistema = SistemaWinrate()

# =========================
# GERADOR DE SINAL
# =========================
def gerar_sinal(simbolo):
    preco = buscar_preco_real(simbolo)
    direcao = random.choice(["COMPRA", "VENDA"])

    sinal = {
        "id": f"{simbolo}_{int(time.time())}_{random.randint(1000,9999)}",
        "simbolo": simbolo,
        "direcao": direcao,
        "preco": round(preco, 2),
        "hora": datetime.now().strftime("%H:%M"),
        "resultado": None,
        "profit": 0.0,
        "simulado": MODO_SIMULACAO
    }

    sistema.adicionar(sinal)

    def simular():
        time.sleep(random.randint(10, 30))
        if MODO_SIMULACAO:
            win = random.random() < WINRATE_SIMULADO
            resultado = "WIN" if win else "LOSS"
            profit = random.uniform(2, 6) if win else random.uniform(1, 4)
            sistema.fechar(sinal["id"], resultado, profit)

    threading.Thread(target=simular, daemon=True).start()
    return sinal

# =========================
# TELEGRAM
# =========================
def enviar_telegram(sinal):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return

    aviso = "⚠️ *SINAL SIMULADO (DEMO)*\n" if MODO_SIMULACAO else ""
    texto = f"""{aviso}
📊 *{sinal['direcao']}* {sinal['simbolo']}
💰 Preço: ${sinal['preco']}
⏰ Hora: {sinal['hora']}
"""

    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": texto, "parse_mode": "Markdown"},
        timeout=10
    )

# =========================
# ROTAS
# =========================
@app.route("/")
def home():
    return jsonify({
        "stats": sistema.get_stats(),
        "ultimos_sinais": sistema.historico(10),
        "modo": "SIMULAÇÃO" if MODO_SIMULACAO else "REAL"
    })

@app.route("/gerar")
def gerar():
    simbolos = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
    s = gerar_sinal(random.choice(simbolos))
    enviar_telegram(s)
    return jsonify(s)

# =========================
# WORKER
# =========================
def worker():
    logger.info("🤖 Bot iniciado")
    simbolos = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]

    while True:
        for s in simbolos:
            if random.random() < 0.3:
                sinal = gerar_sinal(s)
                enviar_telegram(sinal)
            time.sleep(1)
        time.sleep(BOT_INTERVAL)

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=False)
