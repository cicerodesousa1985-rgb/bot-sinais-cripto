
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
from binance.client import Client
from binance.enums import *

# =========================
# CONFIGURAÇÃO
# =========================
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
PORT = int(os.getenv("PORT", "10000"))

LEVERAGE = 10
MARGIN_TYPE = "ISOLATED"
PARES = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "MATICUSDT", "LINKUSDT", "AVAXUSDT", "DOTUSDT"]

try:
    binance_client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)
    logger.info("✅ Binance Conectada")
except:
    binance_client = None

# =========================
# SISTEMA DE DADOS E WINRATE
# =========================
class BotData:
    def __init__(self):
        self.sinais = deque(maxlen=30)
        self.stats = {
            "total": 0,
            "wins": 0,
            "losses": 0,
            "winrate": 0.0,
            "saldo_real": 0.0,
            "inicio": datetime.now().strftime("%d/%m %H:%M")
        }
    
    def add_sinal(self, sinal):
        self.sinais.append(sinal)
        self.stats["total"] += 1
        self.atualizar_winrate()
        return sinal

    def atualizar_winrate(self):
        total_fechados = self.stats["wins"] + self.stats["losses"]
        if total_fechados > 0:
            self.stats["winrate"] = (self.stats["wins"] / total_fechados) * 100

    def atualizar_saldo(self):
        if not binance_client: return
        try:
            acc = binance_client.futures_account()
            self.stats["saldo_real"] = float(acc['totalWalletBalance'])
        except: pass

bot_data = BotData()

# =========================
# EXECUÇÃO BINANCE
# =========================
def trade_binance(sinal):
    if not binance_client: return False
    try:
        simbolo = sinal['simbolo']
        binance_client.futures_change_leverage(symbol=simbolo, leverage=LEVERAGE)
        try: binance_client.futures_change_margin_type(symbol=simbolo, marginType=MARGIN_TYPE)
        except: pass

        info = binance_client.futures_exchange_info()
        s_info = next(i for i in info['symbols'] if i['symbol'] == simbolo)
        qty_precision = s_info['quantityPrecision']
        price_precision = s_info['pricePrecision']

        quantidade = round(5.5 / sinal['preco'], qty_precision)
        side = SIDE_BUY if sinal['direcao'] == "COMPRA" else SIDE_SELL
        side_inv = SIDE_SELL if sinal['direcao'] == "COMPRA" else SIDE_BUY

        binance_client.futures_create_order(symbol=simbolo, side=side, type=FUTURE_ORDER_TYPE_MARKET, quantity=quantidade)
        
        tp = round(sinal['tp'], price_precision)
        sl = round(sinal['sl'], price_precision)
        
        binance_client.futures_create_order(symbol=simbolo, side=side_inv, type=FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET, stopPrice=tp, closePosition=True)
        binance_client.futures_create_order(symbol=simbolo, side=side_inv, type=FUTURE_ORDER_TYPE_STOP_MARKET, stopPrice=sl, closePosition=True)
        
        return True
    except Exception as e:
        logger.error(f"Erro Trade: {e}")
        return False

# =========================
# LÓGICA DE SINAIS
# =========================
def gerar_sinal():
    simbolo = random.choice(PARES)
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={simbolo}").json()
        preco = float(res['price'])
        direcao = random.choice(["COMPRA", "VENDA"])
        
        sinal = {
            "id": int(time.time()),
            "simbolo": simbolo,
            "direcao": direcao,
            "preco": preco,
            "tp": preco * 1.006 if direcao == "COMPRA" else preco * 0.994,
            "sl": preco * 0.992 if direcao == "COMPRA" else preco * 1.008,
            "tempo": datetime.now().strftime("%H:%M:%S"),
            "executado": False
        }
        
        sucesso = trade_binance(sinal)
        sinal['executado'] = sucesso
        bot_data.add_sinal(sinal)
        bot_data.atualizar_saldo()
        
        if TELEGRAM_TOKEN:
            status = "✅ EXECUTADO" if sucesso else "❌ ERRO/SALDO"
            msg = f"🤖 *SINAL {simbolo}*\n📈 Direção: {direcao}\n💰 Preço: {preco}\n🎯 Status: {status}"
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

def worker():
    bot_data.atualizar_saldo()
    while True:
        gerar_sinal()
        time.sleep(300) # 5 minutos entre sinais para gerenciar banca pequena

# =========================
# DASHBOARD FINAL
# =========================
DASHBOARD_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>FAT PIG - DASHBOARD REAL</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        body { background: #0a0a0a; color: #f0f0f0; font-family: 'Segoe UI', sans-serif; }
        .navbar { background: #111; border-bottom: 3px solid #ffdf00; }
        .card-main { background: #151515; border: 1px solid #333; border-radius: 15px; }
        .text-gold { color: #ffdf00; }
        .winrate-circle { width: 100px; height: 100px; border-radius: 50%; border: 5px solid #ffdf00; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 1.2em; margin: 0 auto; }
        .signal-item { background: #1a1a1a; border-radius: 10px; padding: 15px; margin-bottom: 10px; border-left: 4px solid #ffdf00; }
        .status-badge { font-size: 0.7em; padding: 4px 8px; border-radius: 5px; }
    </style>
</head>
<body>
    <nav class="navbar navbar-dark mb-4">
        <div class="container">
            <span class="navbar-brand h1"><i class="fas fa-chart-line text-gold"></i> FAT PIG <span class="text-gold">REAL-TIME</span></span>
            <span class="badge bg-success">SISTEMA ATIVO</span>
        </div>
    </nav>

    <div class="container">
        <div class="row g-3 mb-4">
            <div class="col-md-4">
                <div class="card-main p-4 text-center">
                    <div class="text-muted small mb-2">SALDO BINANCE FUTURES</div>
                    <div class="h1 text-gold">${{ "%.2f"|format(stats.saldo_real) }}</div>
                    <div class="small text-muted">Atualizado agora</div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card-main p-4 text-center">
                    <div class="text-muted small mb-2">WINRATE ATUAL</div>
                    <div class="winrate-circle">{{ "%.1f"|format(stats.winrate) }}%</div>
                    <div class="mt-2 small">{{stats.wins}}W - {{stats.losses}}L</div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card-main p-4 text-center">
                    <div class="text-muted small mb-2">TOTAL DE SINAIS</div>
                    <div class="h1 text-white">{{stats.total}}</div>
                    <div class="small text-muted">Desde {{stats.inicio}}</div>
                </div>
            </div>
        </div>

        <div class="card-main p-4">
            <h4 class="mb-4"><i class="fas fa-list text-gold"></i> MONITORAMENTO DE SINAIS</h4>
            <div class="row">
                {% for s in sinais|reverse %}
                <div class="col-md-6">
                    <div class="signal-item">
                        <div class="d-flex justify-content-between">
                            <span class="h5 mb-0">{{s.simbolo}}</span>
                            <span class="badge {{ 'bg-success' if s.direcao == 'COMPRA' else 'bg-danger' }}">{{s.direcao}}</span>
                        </div>
                        <div class="mt-2 d-flex justify-content-between align-items-center">
                            <span class="small">Preço: <strong>${{s.preco}}</strong></span>
                            <span class="small text-muted">{{s.tempo}}</span>
                        </div>
                        <div class="mt-2">
                            {% if s.executado %}
                            <span class="text-success small"><i class="fas fa-check-circle"></i> EXECUTADO NA BINANCE</span>
                            {% else %}
                            <span class="text-warning small"><i class="fas fa-exclamation-triangle"></i> AGUARDANDO MARGEM</span>
                            {% endif %}
                        </div>
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
    bot_data.atualizar_saldo()
    return render_template_string(DASHBOARD_HTML, sinais=list(bot_data.sinais), stats=bot_data.stats)

if __name__ == '__main__':
    threading.Thread(target=worker, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT)
