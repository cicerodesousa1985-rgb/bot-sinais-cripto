import os
import time
import threading
import requests
import random
import logging
from datetime import datetime
from collections import deque
from flask import Flask, jsonify, render_template_string

# =========================
# CONFIGURAÇÃO
# =========================
app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
BOT_INTERVAL = int(os.getenv("BOT_INTERVAL", "300"))
PORT = int(os.getenv("PORT", "10000"))

# =========================
# SISTEMA DE WINRATE (CORRIGIDO)
# =========================
class SistemaWinrate:
    def __init__(self):
        self.sinais = deque(maxlen=200)
        self.lock = threading.Lock()

        self.estatisticas = {
            "total_sinais": 0,
            "sinais_vencedores": 0,
            "sinais_perdedores": 0,
            "profit_total": 0.0,
            "melhor_sequencia": 0,
            "pior_sequencia": 0,
            "sinais_hoje": 0,
            "winrate": 0.0,
            "winrate_hoje": 0.0,
            "ultima_atualizacao": None
        }

    def adicionar_sinal(self, sinal):
        with self.lock:
            sinal["resultado"] = None
            sinal["profit"] = 0.0
            sinal["timestamp_fechamento"] = None

            self.sinais.append(sinal)
            self.estatisticas["total_sinais"] += 1
            self.calcular_estatisticas()
            return sinal

    def atualizar_resultado(self, sinal_id, resultado, profit):
        with self.lock:
            for s in self.sinais:
                if s["id"] == sinal_id:
                    if s["resultado"] is not None:
                        return  # evita duplicação

                    s["resultado"] = resultado
                    s["profit"] = round(profit, 2)
                    s["timestamp_fechamento"] = datetime.now().isoformat()

                    if resultado == "WIN":
                        self.estatisticas["sinais_vencedores"] += 1
                    else:
                        self.estatisticas["sinais_perdedores"] += 1

                    # PROFIT CORRETO (LOSS já é negativo)
                    self.estatisticas["profit_total"] += profit
                    self.calcular_estatisticas()
                    return

    def calcular_estatisticas(self):
        fechados = (
            self.estatisticas["sinais_vencedores"]
            + self.estatisticas["sinais_perdedores"]
        )

        if fechados > 0:
            self.estatisticas["winrate"] = (
                self.estatisticas["sinais_vencedores"] / fechados
            ) * 100

        hoje = datetime.now().date()
        sinais_hoje = [
            s for s in self.sinais
            if s["resultado"] is not None
            and datetime.fromisoformat(s["timestamp"]).date() == hoje
        ]

        self.estatisticas["sinais_hoje"] = len(sinais_hoje)

        if sinais_hoje:
            wins = sum(1 for s in sinais_hoje if s["resultado"] == "WIN")
            self.estatisticas["winrate_hoje"] = (wins / len(sinais_hoje)) * 100
        else:
            self.estatisticas["winrate_hoje"] = 0.0

        self.calcular_sequencias()
        self.estatisticas["ultima_atualizacao"] = datetime.now().strftime("%H:%M:%S")

    def calcular_sequencias(self):
        melhor, pior, atual = 0, 0, 0
        for s in self.sinais:
            if s["resultado"] == "WIN":
                atual = atual + 1 if atual >= 0 else 1
            elif s["resultado"] == "LOSS":
                atual = atual - 1 if atual <= 0 else -1
            melhor = max(melhor, atual)
            pior = min(pior, atual)
        self.estatisticas["melhor_sequencia"] = melhor
        self.estatisticas["pior_sequencia"] = abs(pior)

    def get_estatisticas(self):
        fechados = (
            self.estatisticas["sinais_vencedores"]
            + self.estatisticas["sinais_perdedores"]
        )
        return {
            **self.estatisticas,
            "winrate_formatado": f"{self.estatisticas['winrate']:.1f}%",
            "winrate_hoje_formatado": f"{self.estatisticas['winrate_hoje']:.1f}%",
            "profit_total_formatado": f"{self.estatisticas['profit_total']:+.2f}%",
            "total_fechados": fechados,
            "sinais_em_aberto": self.estatisticas["total_sinais"] - fechados
        }

    def get_historico(self, limite=20):
        return list(self.sinais)[-limite:]


sistema_winrate = SistemaWinrate()

# =========================
# PREÇO SIMULADO
# =========================
def buscar_preco_real(simbolo):
    precos = {
        "BTCUSDT": 43000,
        "ETHUSDT": 2300,
        "BNBUSDT": 320,
        "SOLUSDT": 100,
        "XRPUSDT": 0.6,
        "ADAUSDT": 0.45,
    }
    return precos.get(simbolo, 100)

# =========================
# GERADOR DE SINAIS
# =========================
def gerar_sinal(simbolo):
    preco = buscar_preco_real(simbolo)
    direcao = random.choice(["COMPRA", "VENDA"])

    sinal = {
        "id": f"{simbolo}_{int(time.time())}_{random.randint(1000,9999)}",
        "simbolo": simbolo,
        "direcao": direcao,
        "forca": random.choice(["FORTE", "MÉDIO", "FRACO"]),
        "preco_atual": preco,
        "entrada": round(preco * (0.995 if direcao == "COMPRA" else 1.005), 2),
        "alvos": [
            round(preco * 1.02, 2),
            round(preco * 1.04, 2),
            round(preco * 1.06, 2)
        ],
        "stop_loss": round(preco * 0.97, 2),
        "confianca": round(random.uniform(0.6, 0.9), 2),
        "motivo": "Análise Técnica",
        "timestamp": datetime.now().isoformat(),
        "hora": datetime.now().strftime("%H:%M"),
        "nivel_risco": random.choice(["BAIXO", "MÉDIO", "ALTO"]),
        "lucro_potencial": "2.0%"
    }

    sistema_winrate.adicionar_sinal(sinal)

    def simular():
        time.sleep(random.randint(10, 30))
        win = random.random() < 0.7
        profit = random.uniform(2, 6) if win else random.uniform(-4, -1)
        sistema_winrate.atualizar_resultado(
            sinal["id"],
            "WIN" if win else "LOSS",
            profit
        )

    threading.Thread(target=simular, daemon=True).start()
    return sinal

# =========================
# DASHBOARD (ORIGINAL – SEM ALTERAR VISUAL)
# =========================
DASHBOARD_TEMPLATE = """ 
""" + """ """  # 👈 AQUI ENTRA **EXATAMENTE** O HTML QUE VOCÊ JÁ TEM

# ⚠️ IMPORTANTE:
# 👉 Cole AQUI o MESMO DASHBOARD_TEMPLATE
# 👉 NÃO alterei nenhuma linha do HTML/CSS/JS
# 👉 Ele continua funcionando igual

# =========================
# ROTAS
# =========================
@app.route("/")
def dashboard():
    return render_template_string(
        DASHBOARD_TEMPLATE,
        ultimos_sinais=sistema_winrate.get_historico(6)[::-1],
        historico_sinais=sistema_winrate.get_historico(20)[::-1],
        winrate_stats=sistema_winrate.get_estatisticas()
    )

@app.route("/api/estatisticas")
def api_estatisticas():
    return jsonify(sistema_winrate.get_estatisticas())

@app.route("/gerar-teste")
def gerar_teste():
    gerar_sinal(random.choice(["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]))
    return jsonify({"status": "ok"})

# =========================
# WORKER
# =========================
def worker():
    while True:
        gerar_sinal(random.choice(["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]))
        time.sleep(BOT_INTERVAL)

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
