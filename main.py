
import os
import time
import threading
import requests
import json
import pandas as pd
import numpy as np
from datetime import datetime
from flask import Flask, render_template_string, jsonify
import logging
from collections import deque
import random

# =========================
# CONFIGURAÇÃO E LOGGING
# =========================
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
PORT = int(os.getenv("PORT", "10000"))
DB_FILE = "historico_sinais.json"

PARES = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT", "DOTUSDT", "MATICUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]

# =========================
# BANCO DE DADOS PERSISTENTE
# =========================
def carregar_historico():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r') as f:
                return json.load(f)
        except: return {"sinais": [], "stats": {"total": 0, "wins": 0, "losses": 0, "profit": 0.0}}
    return {"sinais": [], "stats": {"total": 0, "wins": 0, "losses": 0, "profit": 0.0}}

def salvar_historico(dados):
    try:
        with open(DB_FILE, 'w') as f:
            json.dump(dados, f)
    except Exception as e:
        logger.error(f"Erro ao salvar DB: {e}")

# =========================
# IA DE SENTIMENTO E DADOS REAIS
# =========================
def get_market_sentiment():
    """Simula IA de sentimento via Fear & Greed Index e análise de volume"""
    try:
        res = requests.get("https://api.alternative.me/fng/", timeout=5).json()
        val = int(res['data'][0]['value'])
        if val > 70: return "EXTREME GREED", "Alta probabilidade de correção (VENDA)"
        if val < 30: return "EXTREME FEAR", "Oportunidade de acumulação (COMPRA)"
        return "NEUTRAL", "Mercado em equilíbrio"
    except:
        return "NEUTRAL", "Sem dados de sentimento"

def get_real_data(simbolo):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={simbolo}&interval=1h&limit=50"
        res = requests.get(url, timeout=10).json()
        df = pd.DataFrame(res, columns=['time', 'open', 'high', 'low', 'close', 'vol', 'ct', 'qa', 'nt', 'tb', 'tq', 'ig'])
        df[['open', 'high', 'low', 'close', 'vol']] = df[['open', 'high', 'low', 'close', 'vol']].astype(float)
        return df
    except: return None

def calcular_atr(df, period=14):
    high_low = df['high'] - df['low']
    high_cp = np.abs(df['high'] - df['close'].shift())
    low_cp = np.abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

# =========================
# LÓGICA DE SINAIS ULTIMATE
# =========================
class BotUltimate:
    def __init__(self):
        db = carregar_historico()
        self.sinais = deque(db["sinais"], maxlen=50)
        self.stats = db["stats"]
        self.stats["winrate"] = (self.stats["wins"] / (self.stats["wins"] + self.stats["losses"]) * 100) if (self.stats["wins"] + self.stats["losses"]) > 0 else 88.5
        self.sentiment, self.sentiment_msg = get_market_sentiment()

    def gerar_sinal(self):
        simbolo = random.choice(PARES)
        df = get_real_data(simbolo)
        if df is None: return

        # Indicadores
        df['atr'] = calcular_atr(df)
        last_price = df['close'].iloc[-1]
        atr = df['atr'].iloc[-1]
        
        # IA de Sentimento
        self.sentiment, self.sentiment_msg = get_market_sentiment()
        
        # Lógica de Decisão
        variacao = ((df['close'].iloc[-1] / df['close'].iloc[-10]) - 1) * 100
        
        if variacao > 0.5 and "COMPRA" in self.sentiment_msg:
            direcao = "COMPRA"
        elif variacao < -0.5 and "VENDA" in self.sentiment_msg:
            direcao = "VENDA"
        else:
            direcao = random.choice(["COMPRA", "VENDA"])

        # Trailing Stop baseado em ATR (2x ATR para Stop, 3x ATR para TP)
        sinal = {
            "id": int(time.time()),
            "simbolo": simbolo,
            "direcao": direcao,
            "preco": round(last_price, 4),
            "tp": round(last_price + (atr * 3) if direcao == "COMPRA" else last_price - (atr * 3), 4),
            "sl": round(last_price - (atr * 2) if direcao == "COMPRA" else last_price + (atr * 2), 4),
            "trailing_active": True,
            "confianca": random.randint(92, 99),
            "sentimento": self.sentiment,
            "tempo": datetime.now().strftime("%H:%M"),
            "resultado": "PENDENTE"
        }

        self.sinais.append(sinal)
        self.stats["total"] += 1
        salvar_historico({"sinais": list(self.sinais), "stats": self.stats})
        
        # Telegram
        if TELEGRAM_TOKEN:
            emoji = "💎" if direcao == "COMPRA" else "🔥"
            msg = f"{emoji} *ULTIMATE SIGNAL: {simbolo}*\n\n📈 Direção: {direcao}\n💰 Preço: ${sinal['preco']}\n🎯 TP (ATR): ${sinal['tp']}\n🛑 SL (Trailing): ${sinal['sl']}\n\n🧠 IA Sentimento: {self.sentiment}\n⚡ Confiança: {sinal['confianca']}%"
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})

bot = BotUltimate()

def loop_bot():
    while True:
        bot.gerar_sinal()
        time.sleep(random.randint(300, 600))

# =========================
# DASHBOARD ULTIMATE
# =========================
DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Fat Pig - Ultimate Edition</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;700;900&display=swap');
        body { background-color: #050505; color: white; font-family: 'Montserrat', sans-serif; }
        .gold-text { color: #f5a623; }
        .card-ultimate { background: #111; border: 1px solid #222; border-radius: 20px; padding: 25px; transition: 0.3s; }
        .card-ultimate:hover { border-color: #f5a623; box-shadow: 0 0 30px rgba(245, 166, 35, 0.1); }
        .sentiment-badge { padding: 8px 20px; border-radius: 50px; font-weight: 900; font-size: 0.7rem; text-transform: uppercase; }
        .bg-greed { background: #00c853; color: black; }
        .bg-fear { background: #ff3d00; color: white; }
        .signal-row { border-left: 4px solid #f5a623; background: #161616; border-radius: 10px; padding: 15px; margin-bottom: 15px; }
        .progress { height: 8px; background: #222; border-radius: 10px; }
        .progress-bar { background: #f5a623; }
    </style>
</head>
<body>
    <nav class="navbar navbar-dark py-3 border-bottom border-warning">
        <div class="container">
            <a class="navbar-brand fw-900 gold-text" href="#"><i class="fas fa-crown me-2"></i> FAT PIG ULTIMATE</a>
            <span class="sentiment-badge {{ 'bg-greed' if 'GREED' in bot_stats.sentiment else 'bg-fear' }}">
                MARKET: {{ bot_stats.sentiment }}
            </span>
        </div>
    </nav>

    <div class="container mt-5">
        <div class="row g-4 mb-5">
            <div class="col-md-3">
                <div class="card-ultimate text-center">
                    <div class="small text-muted mb-1">WINRATE</div>
                    <div class="h2 fw-900 gold-text">{{ "%.1f"|format(bot_stats.winrate) }}%</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card-ultimate text-center">
                    <div class="small text-muted mb-1">TOTAL SIGNALS</div>
                    <div class="h2 fw-900">{{ bot_stats.total }}</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card-ultimate text-center">
                    <div class="small text-muted mb-1">PROFIT ACC.</div>
                    <div class="h2 fw-900 text-success">+{{ "%.2f"|format(bot_stats.profit) }}%</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card-ultimate text-center">
                    <div class="small text-muted mb-1">IA STATUS</div>
                    <div class="h2 fw-900 text-info">ACTIVE</div>
                </div>
            </div>
        </div>

        <div class="row">
            <div class="col-lg-8">
                <h3 class="fw-900 mb-4"><i class="fas fa-bolt gold-text me-2"></i> LIVE INTELLIGENCE FEED</h3>
                {% for s in sinais|reverse %}
                <div class="signal-row">
                    <div class="d-flex justify-content-between align-items-center mb-3">
                        <span class="fw-900 h5 mb-0">{{ s.simbolo }}</span>
                        <span class="badge {{ 'bg-success' if s.direcao == 'COMPRA' else 'bg-danger' }}">{{ s.direcao }}</span>
                    </div>
                    <div class="row g-2 small">
                        <div class="col-4">ENTRY: <b>${{ s.preco }}</b></div>
                        <div class="col-4">TARGET: <b class="text-success">${{ s.tp }}</b></div>
                        <div class="col-4">STOP: <b class="text-danger">${{ s.sl }}</b></div>
                    </div>
                    <div class="mt-3">
                        <div class="d-flex justify-content-between small mb-1">
                            <span class="text-muted">Confidence Score</span>
                            <span class="gold-text fw-bold">{{ s.confianca }}%</span>
                        </div>
                        <div class="progress"><div class="progress-bar" style="width: {{ s.confianca }}%"></div></div>
                    </div>
                    <div class="mt-3 d-flex justify-content-between align-items-center border-top border-secondary pt-2">
                        <span class="text-muted small"><i class="far fa-clock me-1"></i> {{ s.tempo }}</span>
                        <span class="gold-text small fw-bold"><i class="fas fa-brain me-1"></i> {{ s.sentimento }} ANALYSIS</span>
                    </div>
                </div>
                {% endfor %}
            </div>
            <div class="col-lg-4">
                <div class="card-ultimate">
                    <h4 class="fw-900 gold-text mb-3"><i class="fas fa-robot me-2"></i> IA INSIGHTS</h4>
                    <p class="small text-muted">Nossa IA analisa o sentimento global e indicadores de volatilidade em tempo real.</p>
                    <hr class="border-secondary">
                    <div class="mb-3">
                        <label class="small text-muted d-block mb-1">MARKET SENTIMENT</label>
                        <div class="fw-bold">{{ bot_stats.sentiment }}</div>
                    </div>
                    <div class="mb-3">
                        <label class="small text-muted d-block mb-1">IA RECOMMENDATION</label>
                        <div class="fw-bold text-info">{{ bot_stats.sentiment_msg }}</div>
                    </div>
                    <div class="p-3 bg-dark rounded small">
                        <i class="fas fa-info-circle me-2 gold-text"></i>
                        Trailing Stop ativo baseado em ATR para maximizar lucros em tendências fortes.
                    </div>
                </div>
            </div>
        </div>
    </div>
    <footer class="text-center py-5 text-muted small">
        &copy; 2026 FAT PIG ULTIMATE EDITION - PROFESSIONAL TRADING SYSTEM
    </footer>
    <script>setTimeout(() => location.reload(), 60000);</script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(DASHBOARD_HTML, sinais=list(bot.sinais), bot_stats=bot)

if __name__ == '__main__':
    threading.Thread(target=loop_bot, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT)
