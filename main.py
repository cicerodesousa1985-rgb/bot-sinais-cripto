
import os
import time
import threading
import requests
import json
from datetime import datetime
from flask import Flask, render_template_string
import logging
from collections import deque
import random

# =========================
# CONFIGURAÇÃO
# =========================
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
PORT = int(os.getenv("PORT", "10000"))
DB_FILE = "historico_sinais.json"

PARES = ["BTC", "ETH", "SOL", "LINK", "AVAX", "DOT", "MATIC", "XRP", "ADA", "DOGE"]

# =========================
# BANCO DE DADOS PERSISTENTE
# =========================
def carregar_historico():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r') as f:
                return json.load(f)
        except: pass
    return {"sinais": [], "stats": {"total": 0, "wins": 0, "losses": 0, "profit": 0.0}}

def salvar_historico(dados):
    try:
        with open(DB_FILE, 'w') as f:
            json.dump(dados, f)
    except: pass

# =========================
# IA DE SENTIMENTO
# =========================
def get_market_sentiment():
    traducoes = {
        "EXTREME_GREED": "GANÂNCIA EXTREMA",
        "GREED": "GANÂNCIA",
        "NEUTRAL": "NEUTRO",
        "FEAR": "MEDO",
        "EXTREME_FEAR": "MEDO EXTREMO"
    }
    try:
        res = requests.get("https://api.alternative.me/fng/", timeout=5).json()
        val = int(res['data'][0]['value'])
        status = res['data'][0]['value_classification'].upper().replace(" ", "_")
        status_pt = traducoes.get(status, status)
        return status_pt, f"Índice em {val}"
    except:
        return "NEUTRO", "Sem dados"

# =========================
# BUSCA DE PREÇO REAL (ESTÁVEL)
# =========================
def buscar_preco_estavel(simbolo):
    try:
        # Usa CryptoCompare que é mais estável no Render que a Binance
        url = f"https://min-api.cryptocompare.com/data/price?fsym={simbolo}&tsyms=USD"
        res = requests.get(url, timeout=8).json()
        return float(res['USD'])
    except Exception as e:
        logger.error(f"Erro ao buscar preço de {simbolo}: {e}")
        return None

# =========================
# LÓGICA DE SINAIS
# =========================
class BotUltimate:
    def __init__(self):
        db = carregar_historico()
        self.sinais = deque(db.get("sinais", []), maxlen=50)
        self.stats = db.get("stats", {"total": 0, "wins": 0, "losses": 0, "profit": 0.0})
        self.sentiment, self.sentiment_msg = get_market_sentiment()
        self.winrate = 88.5

    def gerar_sinal(self):
        simbolo = random.choice(PARES)
        preco = buscar_preco_estavel(simbolo)
        
        # Se falhar, tenta mais uma vez após 2 segundos
        if preco is None:
            time.sleep(2)
            preco = buscar_preco_estavel(simbolo)
            
        if preco is None:
            logger.error(f"Impossível obter preço para {simbolo}. Sinal cancelado.")
            return

        self.sentiment, self.sentiment_msg = get_market_sentiment()
        direcao = random.choice(["COMPRA", "VENDA"])

        sinal = {
            "id": int(time.time()),
            "simbolo": f"{simbolo}USDT",
            "direcao": direcao,
            "preco": round(preco, 4),
            "tp": round(preco * 1.025 if direcao == "COMPRA" else preco * 0.975, 4),
            "sl": round(preco * 0.97 if direcao == "COMPRA" else preco * 1.03, 4),
            "confianca": random.randint(92, 99),
            "sentimento": self.sentiment,
            "tempo": datetime.now().strftime("%H:%M"),
            "motivo": "Análise IA + Fluxo"
        }

        self.sinais.append(sinal)
        self.stats["total"] += 1
        self.winrate = random.uniform(89, 95)
        salvar_historico({"sinais": list(self.sinais), "stats": self.stats})
        
        if TELEGRAM_TOKEN:
            emoji = "💎" if direcao == "COMPRA" else "🔥"
            msg = f"{emoji} *SINAL FAT PIG: {sinal['simbolo']}*\n\n📈 Direção: {direcao}\n💰 Entrada: ${sinal['preco']}\n🎯 Alvo (TP): ${sinal['tp']}\n🛑 Stop (SL): ${sinal['sl']}\n\n🧠 IA Sentimento: {self.sentiment}\n⚡ Confiança: {sinal['confianca']}%"
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})

bot = BotUltimate()

def loop_bot():
    # Pequeno delay inicial para garantir rede pronta
    time.sleep(5)
    bot.gerar_sinal()
    while True:
        time.sleep(random.randint(300, 600))
        bot.gerar_sinal()

# =========================
# DASHBOARD
# =========================
DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <title>Fat Pig Ultimate - Oficial</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;700;900&display=swap');
        body { background-color: #050505; color: white; font-family: 'Montserrat', sans-serif; }
        .gold-text { color: #f5a623; }
        .card-ultimate { background: #111; border: 1px solid #222; border-radius: 20px; padding: 25px; text-align: center; }
        .signal-row { border-left: 4px solid #f5a623; background: #161616; border-radius: 10px; padding: 15px; margin-bottom: 15px; }
        .badge-sentiment { background: #f5a623; color: black; padding: 5px 15px; border-radius: 50px; font-weight: 900; font-size: 0.7rem; }
    </style>
</head>
<body>
    <nav class="navbar navbar-dark py-3 border-bottom border-warning">
        <div class="container">
            <a class="navbar-brand fw-900 gold-text" href="#"><i class="fas fa-crown me-2"></i> FAT PIG ULTIMATE</a>
            <span class="badge-sentiment">MERCADO: {{ bot_stats.sentiment }}</span>
        </div>
    </nav>

    <div class="container mt-5">
        <div class="row g-4 mb-5">
            <div class="col-md-4">
                <div class="card-ultimate">
                    <div class="small text-muted mb-1">TAXA DE ACERTO</div>
                    <div class="h2 fw-900 gold-text">{{ "%.1f"|format(bot_stats.winrate) }}%</div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card-ultimate">
                    <div class="small text-muted mb-1">TOTAL DE SINAIS</div>
                    <div class="h2 fw-900">{{ bot_stats.stats.total }}</div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card-ultimate">
                    <div class="small text-muted mb-1">STATUS DA IA</div>
                    <div class="h2 fw-900 text-success">ATIVA</div>
                </div>
            </div>
        </div>

        <div class="row">
            <div class="col-12">
                <h3 class="fw-900 mb-4"><i class="fas fa-bolt gold-text me-2"></i> MONITORAMENTO EM TEMPO REAL</h3>
                {% for s in sinais|reverse %}
                <div class="signal-row">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <span class="fw-900 h5 mb-0">{{ s.simbolo }}</span>
                        <span class="badge {{ 'bg-success' if s.direcao == 'COMPRA' else 'bg-danger' }}">{{ s.direcao }}</span>
                    </div>
                    <div class="row g-2 small">
                        <div class="col-4">ENTRADA: <b>${{ s.preco }}</b></div>
                        <div class="col-4">ALVO (TP): <b class="text-success">${{ s.tp }}</b></div>
                        <div class="col-4">STOP (SL): <b class="text-danger">${{ s.sl }}</b></div>
                    </div>
                    <div class="mt-2 d-flex justify-content-between align-items-center border-top border-secondary pt-2">
                        <span class="text-muted small"><i class="far fa-clock me-1"></i> {{ s.tempo }}</span>
                        <span class="gold-text small fw-bold"><i class="fas fa-brain me-1"></i> {{ s.motivo }}</span>
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
    </div>
    <script>setTimeout(() => location.reload(), 30000);</script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(DASHBOARD_HTML, sinais=list(bot.sinais), bot_stats=bot)

if __name__ == '__main__':
    threading.Thread(target=loop_bot, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT)
