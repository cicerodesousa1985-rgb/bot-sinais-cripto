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

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY") or os.getenv("API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET") or os.getenv("BINANCE_SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PORT = int(os.getenv("PORT", "10000"))

LEVERAGE = 10
MARGIN_TYPE = "ISOLATED"
PARES = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "MATICUSDT", "LINKUSDT", "AVAXUSDT", "DOTUSDT"]

def get_binance_client():
    try:
        if not BINANCE_API_KEY or not BINANCE_API_SECRET:
            return None, "Chaves ausentes no Render"
        
        # Tenta usar o endpoint alternativo da Binance (fapi.binance.com)
        client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)
        # Força o uso de uma URL alternativa se a principal falhar
        client.FUTURES_URL = 'https://fapi.binance.com/fapi'
        
        # Testa a conexão com uma chamada simples
        client.futures_ping()
        return client, "Conectado ✅"
    except Exception as e:
        return None, f"Erro: {str(e)[:30]}"

binance_client, status_inicial = get_binance_client()

# =========================
# SISTEMA DE DADOS
# =========================
class BotData:
    def __init__(self):
        self.sinais = deque(maxlen=30)
        self.stats = {
            "total": 0, "wins": 0, "losses": 0, "winrate": 0.0,
            "saldo_real": 0.0, "inicio": datetime.now().strftime("%d/%m %H:%M"),
            "status_api": status_inicial
        }
    
    def add_sinal(self, sinal):
        self.sinais.append(sinal)
        self.stats["total"] += 1
        return sinal

    def atualizar_saldo(self):
        global binance_client
        if not binance_client:
            binance_client, self.stats["status_api"] = get_binance_client()
        
        if binance_client:
            try:
                # Tenta buscar o saldo de forma mais direta
                res = binance_client.futures_account_balance()
                for item in res:
                    if item['asset'] == 'USDT':
                        self.stats["saldo_real"] = float(item['balance'])
                        self.stats["status_api"] = "Conectado ✅"
                        break
            except Exception as e:
                self.stats["status_api"] = f"Erro Conexão: {str(e)[:20]}"

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

        quantidade = round(5.2 / sinal['preco'], qty_precision)
        side = SIDE_BUY if sinal['direcao'] == "COMPRA" else SIDE_SELL
        side_inv = SIDE_SELL if sinal['direcao'] == "COMPRA" else SIDE_BUY

        binance_client.futures_create_order(symbol=simbolo, side=side, type=FUTURE_ORDER_TYPE_MARKET, quantity=quantidade)
        
        tp = round(sinal['tp'], price_precision)
        sl = round(sinal['sl'], price_precision)
        
        binance_client.futures_create_order(symbol=simbolo, side=side_inv, type=FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET, stopPrice=tp, closePosition=True)
        binance_client.futures_create_order(symbol=simbolo, side=side_inv, type=FUTURE_ORDER_TYPE_STOP_MARKET, stopPrice=sl, closePosition=True)
        
        return True
    except: return False

# =========================
# LÓGICA DE SINAIS
# =========================
def gerar_sinal():
    simbolo = random.choice(PARES)
    try:
        # Busca preço via API pública (mais estável)
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={simbolo}", timeout=5).json()
        preco = float(res['price'])
        direcao = random.choice(["COMPRA", "VENDA"])
        
        sinal = {
            "id": int(time.time()), "simbolo": simbolo, "direcao": direcao, "preco": preco,
            "tp": preco * 1.005 if direcao == "COMPRA" else preco * 0.995,
            "sl": preco * 0.99 if direcao == "COMPRA" else preco * 1.01,
            "tempo": datetime.now().strftime("%H:%M:%S"), "executado": False
        }
        
        sinal['executado'] = trade_binance(sinal)
        bot_data.add_sinal(sinal)
        bot_data.atualizar_saldo()
        
        if TELEGRAM_TOKEN:
            status = "✅ EXECUTADO" if sinal['executado'] else "❌ FALHA"
            msg = f"🤖 *SINAL {simbolo}*\n📈 Direção: {direcao}\n💰 Preço: {preco}\n🎯 Status: {status}"
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

def worker():
    while True:
        bot_data.atualizar_saldo()
        gerar_sinal()
        time.sleep(60)

# =========================
# DASHBOARD
# =========================
DASHBOARD_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>FAT PIG - V5 FIX</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background: #0a0a0a; color: #f0f0f0; font-family: sans-serif; }
        .card-main { background: #151515; border: 1px solid #333; border-radius: 15px; padding: 20px; text-align: center; }
        .text-gold { color: #ffdf00; }
        .signal-item { background: #1a1a1a; border-radius: 10px; padding: 15px; margin-bottom: 10px; border-left: 4px solid #ffdf00; }
    </style>
</head>
<body>
    <div class="container mt-4">
        <h2 class="text-center mb-4 text-gold">🇧🇷 FAT PIG - V5 (FIX CONEXÃO)</h2>
        <div class="row g-3 mb-4">
            <div class="col-md-6">
                <div class="card-main">
                    <div class="text-muted small">SALDO BINANCE FUTURES</div>
                    <div class="h1 text-gold">${{ "%.2f"|format(stats.saldo_real) }}</div>
                    <div class="badge bg-info">{{ stats.status_api }}</div>
                </div>
            </div>
            <div class="col-md-6">
                <div class="card-main">
                    <div class="text-muted small">SINAIS GERADOS</div>
                    <div class="h1 text-white">{{ stats.total }}</div>
                    <div class="small">Frequência: 1 min</div>
                </div>
            </div>
        </div>
        <div class="card-main text-start">
            <h4 class="text-gold mb-3">LOG DE OPERAÇÕES</h4>
            {% for s in sinais|reverse %}
            <div class="signal-item">
                <div class="d-flex justify-content-between">
                    <strong>{{s.simbolo}} - {{s.direcao}}</strong>
                    <span>${{s.preco}}</span>
                </div>
                <div class="small mt-1">
                    {% if s.executado %}<span class="text-success">✅ EXECUTADO</span>
                    {% else %}<span class="text-danger">❌ FALHA (VERIFICAR CONEXÃO)</span>{% endif %}
                    <span class="float-end text-muted">{{s.tempo}}</span>
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
