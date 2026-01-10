
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
# CONFIGURAÇÃO E LOGGING
# =========================
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Variáveis de Ambiente
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
PORT = int(os.getenv("PORT", "10000"))

# Configurações de Trade
LEVERAGE = 10
MARGIN_TYPE = "ISOLATED"
PARES = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "MATICUSDT", "LINKUSDT", "AVAXUSDT", "DOTUSDT"]

# Inicializar Binance
try:
    binance_client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)
    logger.info("✅ Binance Conectada")
except:
    binance_client = None
    logger.warning("⚠️ Binance não conectada")

# =========================
# SISTEMA DE DADOS
# =========================
class BotData:
    def __init__(self):
        self.sinais = deque(maxlen=20)
        self.stats = {
            "total": 0,
            "sucesso_binance": 0,
            "erros": 0,
            "winrate": 0.0,
            "inicio": datetime.now().strftime("%d/%m %H:%M")
        }
    
    def add_sinal(self, sinal):
        self.sinais.append(sinal)
        self.stats["total"] += 1
        if sinal.get('executado'): self.stats["sucesso_binance"] += 1
        else: self.stats["erros"] += 1
        return sinal

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

        # Valor nominal mínimo de 5.2 USDT para garantir
        quantidade = round(5.2 / sinal['preco'], qty_precision)
        
        side = SIDE_BUY if sinal['direcao'] == "COMPRA" else SIDE_SELL
        side_inv = SIDE_SELL if sinal['direcao'] == "COMPRA" else SIDE_BUY

        # Ordem Principal
        binance_client.futures_create_order(symbol=simbolo, side=side, type=FUTURE_ORDER_TYPE_MARKET, quantity=quantidade)
        
        # TP e SL
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
def gerar_sinal(simbolo=None):
    if not simbolo: simbolo = random.choice(PARES)
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={simbolo}").json()
        preco = float(res['price'])
        direcao = random.choice(["COMPRA", "VENDA"])
        
        sinal = {
            "id": int(time.time()),
            "simbolo": simbolo,
            "direcao": direcao,
            "preco": preco,
            "tp": preco * 1.005 if direcao == "COMPRA" else preco * 0.995,
            "sl": preco * 0.99 if direcao == "COMPRA" else preco * 1.01,
            "tempo": datetime.now().strftime("%H:%M:%S"),
            "executado": False
        }
        
        sucesso = trade_binance(sinal)
        sinal['executado'] = sucesso
        bot_data.add_sinal(sinal)
        
        if TELEGRAM_TOKEN:
            status = "✅ EXECUTADO" if sucesso else "❌ ERRO/SALDO"
            msg = f"🤖 *SINAL {simbolo}*\n📈 Direção: {direcao}\n💰 Preço: {preco}\n🎯 Status: {status}"
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

def worker():
    # Gera sinal imediato ao iniciar
    gerar_sinal("BTCUSDT")
    while True:
        gerar_sinal()
        time.sleep(180) # A cada 3 minutos um novo sinal

# =========================
# DASHBOARD PREMIUM
# =========================
DASHBOARD_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>FAT PIG PREMIUM</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        body { background: #0f0f0f; color: #e0e0e0; font-family: 'Inter', sans-serif; }
        .navbar { background: #1a1a1a; border-bottom: 2px solid #ffdf00; }
        .card-stat { background: #1a1a1a; border: none; border-radius: 15px; transition: 0.3s; }
        .card-stat:hover { transform: translateY(-5px); background: #252525; }
        .text-gold { color: #ffdf00; }
        .signal-card { background: #1a1a1a; border-radius: 12px; margin-bottom: 15px; border-left: 5px solid #ffdf00; padding: 15px; }
        .badge-buy { background: #00ff8822; color: #00ff88; border: 1px solid #00ff88; }
        .badge-sell { background: #ff475722; color: #ff4757; border: 1px solid #ff4757; }
        .status-ok { color: #00ff88; font-weight: bold; font-size: 0.8em; }
    </style>
</head>
<body>
    <nav class="navbar navbar-dark mb-4">
        <div class="container">
            <span class="navbar-brand mb-0 h1"><i class="fas fa-piggy-bank text-gold"></i> FAT PIG <span class="text-gold">PREMIUM</span></span>
            <span class="text-muted small">Iniciado em: {{stats.inicio}}</span>
        </div>
    </nav>

    <div class="container">
        <div class="row g-3 mb-4">
            <div class="col-md-4">
                <div class="card-stat p-3 text-center">
                    <div class="text-muted small">TOTAL DE SINAIS</div>
                    <div class="h2 text-gold">{{stats.total}}</div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card-stat p-3 text-center">
                    <div class="text-muted small">EXECUTADOS BINANCE</div>
                    <div class="h2 text-success">{{stats.sucesso_binance}}</div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card-stat p-3 text-center">
                    <div class="text-muted small">STATUS DO BOT</div>
                    <div class="h2 text-info"><i class="fas fa-robot"></i> ATIVO</div>
                </div>
            </div>
        </div>

        <h4 class="mb-3"><i class="fas fa-bolt text-gold"></i> ÚLTIMOS SINAIS</h4>
        <div class="row">
            {% for s in sinais|reverse %}
            <div class="col-md-6">
                <div class="signal-card">
                    <div class="d-flex justify-content-between align-items-center">
                        <h5 class="mb-0">{{s.simbolo}}</h5>
                        <span class="badge {{ 'badge-buy' if s.direcao == 'COMPRA' else 'badge-sell' }}">{{s.direcao}}</span>
                    </div>
                    <div class="mt-2 small">
                        <div class="d-flex justify-content-between">
                            <span>Preço: <strong>${{s.preco}}</strong></span>
                            <span>Hora: {{s.tempo}}</span>
                        </div>
                        <div class="mt-1">
                            {% if s.executado %}
                            <span class="status-ok"><i class="fas fa-check-circle"></i> ORDEM ENVIADA PARA BINANCE</span>
                            {% else %}
                            <span class="text-danger small"><i class="fas fa-times-circle"></i> ERRO NA EXECUÇÃO (SALDO?)</span>
                            {% endif %}
                        </div>
                    </div>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
    <script>setTimeout(() => location.reload(), 30000);</script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(DASHBOARD_HTML, sinais=list(bot_data.sinais), stats=bot_data.stats)

if __name__ == '__main__':
    threading.Thread(target=worker, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT)
