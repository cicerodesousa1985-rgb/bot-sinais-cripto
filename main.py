# =========================
# IMPORTS
# =========================
import os
import time
import threading
import requests
import random
import logging
import sqlite3
from datetime import datetime
from flask import Flask, jsonify, render_template_string
from collections import deque
from threading import Lock
python
Copiar código
# =========================
# CONFIGURAÇÕES
# =========================
app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
BOT_INTERVAL = int(os.getenv("BOT_INTERVAL", "300"))
PORT = int(os.getenv("PORT", "10000"))

MODO_DEMO = True
CACHE_PRECO_SEGUNDOS = 60
DB_FILE = "winrate.db"
python
Copiar código
# =========================
# LOG
# =========================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
python
Copiar código
# =========================
# BANCO DE DADOS
# =========================
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS sinais (
            id TEXT PRIMARY KEY,
            simbolo TEXT,
            direcao TEXT,
            preco REAL,
            resultado TEXT,
            profit REAL,
            timestamp TEXT
        )
        """)
init_db()
python
Copiar código
# =========================
# CACHE DE PREÇOS
# =========================
precos_cache = {}

def buscar_preco_real(simbolo):
    agora = time.time()
    if simbolo in precos_cache:
        preco, ts = precos_cache[simbolo]
        if agora - ts < CACHE_PRECO_SEGUNDOS:
            return preco

    try:
        mapa = {
            "BTCUSDT": "bitcoin",
            "ETHUSDT": "ethereum",
            "BNBUSDT": "binancecoin",
            "SOLUSDT": "solana",
        }
        coin = mapa.get(simbolo)
        if coin:
            r = requests.get(
                f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd",
                timeout=10
            )
            if r.status_code == 200:
                preco = float(r.json()[coin]["usd"])
                precos_cache[simbolo] = (preco, agora)
                return preco
    except:
        pass

    return 100.0
python
Copiar código
# =========================
# SISTEMA DE WINRATE (THREAD SAFE + SQLITE)
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
        self.carregar_db()

    def carregar_db(self):
        with sqlite3.connect(DB_FILE) as conn:
            rows = conn.execute("SELECT * FROM sinais").fetchall()
            for r in rows:
                self.stats["total"] += 1
                if r[3] == "WIN":
                    self.stats["wins"] += 1
                elif r[3] == "LOSS":
                    self.stats["loss"] += 1
                self.stats["profit"] += r[4] or 0

    def adicionar(self, sinal):
        with self.lock:
            self.sinais.append(sinal)
            self.stats["total"] += 1

    def fechar(self, sinal, resultado, profit):
        with self.lock:
            sinal["resultado"] = resultado
            sinal["profit"] = profit

            if resultado == "WIN":
                self.stats["wins"] += 1
            else:
                self.stats["loss"] += 1

            self.stats["profit"] += profit

            with sqlite3.connect(DB_FILE) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO sinais VALUES (?,?,?,?,?,?)",
                    (
                        sinal["id"],
                        sinal["simbolo"],
                        sinal["direcao"],
                        resultado,
                        profit,
                        datetime.now().isoformat()
                    )
                )
python
Copiar código
    def estatisticas(self):
        total_fechado = self.stats["wins"] + self.stats["loss"]
        winrate = (self.stats["wins"] / total_fechado * 100) if total_fechado else 0
        return {
            "winrate": winrate,
            "winrate_formatado": f"{winrate:.1f}%",
            "profit_total": self.stats["profit"],
            "profit_total_formatado": f"{self.stats['profit']:+.2f}",
            "sinais_vencedores": self.stats["wins"],
            "sinais_perdedores": self.stats["loss"],
            "total_fechados": total_fechado,
            "sinais_em_aberto": self.stats["total"] - total_fechado,
            "ultima_atualizacao": datetime.now().strftime("%H:%M:%S")
        }

    def historico(self, n=20):
        with self.lock:
            return list(self.sinais)[-n:]
python
Copiar código
sistema = SistemaWinrate()
python
Copiar código
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
        "preco_atual": preco,
        "hora": datetime.now().strftime("%H:%M"),
        "resultado": None,
        "profit": None
    }

    sistema.adicionar(sinal)

    if MODO_DEMO:
        def simular():
            time.sleep(random.randint(20, 60))
            win = random.random() < 0.7
            resultado = "WIN" if win else "LOSS"
            profit = random.uniform(2, 6) if win else -random.uniform(1, 4)
            sistema.fechar(sinal, resultado, profit)

        threading.Thread(target=simular, daemon=True).start()

    return sinal
python
Copiar código
# =========================
# ROTAS
# =========================
@app.route("/")
def dashboard():
    return render_template_string(
        DASHBOARD_TEMPLATE,
        ultimos_sinais=sistema.historico(6),
        historico_sinais=sistema.historico(20),
        winrate_stats=sistema.estatisticas()
    )

@app.route("/api/estatisticas")
def api_stats():
    return jsonify(sistema.estatisticas())
python
Copiar código
# =========================
# WORKER
# =========================
def worker():
    logger.info("🤖 Bot ativo")
    simbolos = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
    while True:
        for s in simbolos:
            if random.random() < 0.25:
                gerar_sinal(s)
            time.sleep(1)
        time.sleep(BOT_INTERVAL)
python
Copiar código
# =========================
# MAIN
# =========================
if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=False)
