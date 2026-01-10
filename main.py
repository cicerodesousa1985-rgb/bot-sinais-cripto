
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

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configurações de Ambiente
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
BOT_INTERVAL = int(os.getenv("BOT_INTERVAL", "300"))
PORT = int(os.getenv("PORT", "10000"))

# Configurações de Trade
LEVERAGE = 10
MARGIN_TYPE = "ISOLATED"
USDT_MARGIN_PER_TRADE = 6.0 

# Inicializar Cliente Binance
try:
    if BINANCE_API_KEY and BINANCE_API_SECRET:
        binance_client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)
        logger.info("✅ Conectado à Binance com sucesso")
    else:
        logger.warning("⚠️ Chaves da Binance não encontradas.")
        binance_client = None
except Exception as e:
    logger.error(f"❌ Erro ao conectar na Binance: {e}")
    binance_client = None

# =========================
# SISTEMA DE WINRATE
# =========================
class SistemaWinrate:
    def __init__(self):
        self.sinais = deque(maxlen=100)
        self.estatisticas = {
            "total_sinais": 0,
            "sinais_vencedores": 0,
            "sinais_perdedores": 0,
            "winrate": 0.0,
            "profit_total": 0.0,
            "melhor_sequencia": 0,
            "pior_sequencia": 0,
            "sinais_hoje": 0,
            "winrate_hoje": 0.0,
            "ultima_atualizacao": None
        }
    
    def adicionar_sinal(self, sinal, resultado=None):
        sinal_completo = {
            **sinal,
            "resultado": resultado,
            "timestamp_fechamento": None,
            "profit": 0.0,
            "executado_binance": False
        }
        self.sinais.append(sinal_completo)
        self.estatisticas["total_sinais"] += 1
        self.calcular_estatisticas()
        return sinal_completo

    def atualizar_execucao(self, sinal_id, status):
        for s in self.sinais:
            if s['id'] == sinal_id:
                s['executado_binance'] = status
                break

    def calcular_estatisticas(self):
        total = self.estatisticas["sinais_vencedores"] + self.estatisticas["sinais_perdedores"]
        if total > 0:
            self.estatisticas["winrate"] = (self.estatisticas["sinais_vencedores"] / total) * 100
        self.estatisticas["ultima_atualizacao"] = datetime.now().strftime("%H:%M:%S")

    def get_estatisticas(self):
        return {
            **self.estatisticas,
            "winrate_formatado": f"{self.estatisticas['winrate']:.1f}%",
            "winrate_hoje_formatado": f"{self.estatisticas['winrate_hoje']:.1f}%",
            "profit_total_formatado": f"${self.estatisticas['profit_total']:+.2f}",
            "total_fechados": self.estatisticas["sinais_vencedores"] + self.estatisticas["sinais_perdedores"],
            "sinais_em_aberto": self.estatisticas["total_sinais"] - (self.estatisticas["sinais_vencedores"] + self.estatisticas["sinais_perdedores"])
        }

    def get_historico(self, limite=20):
        return list(self.sinais)[-limite:]

sistema_winrate = SistemaWinrate()

# =========================
# EXECUÇÃO DE ORDENS BINANCE
# =========================
def configurar_alavancagem(simbolo):
    try:
        binance_client.futures_change_margin_type(symbol=simbolo, marginType=MARGIN_TYPE)
    except: pass
    try:
        binance_client.futures_change_leverage(symbol=simbolo, leverage=LEVERAGE)
    except: pass

def executar_trade_binance(sinal):
    if not binance_client: return False
    simbolo = sinal['simbolo']
    try:
        configurar_alavancagem(simbolo)
        info = binance_client.futures_exchange_info()
        symbol_info = next(item for item in info['symbols'] if item['symbol'] == simbolo)
        qty_precision = symbol_info['quantityPrecision']
        price_precision = symbol_info['pricePrecision']

        valor_nominal = USDT_MARGIN_PER_TRADE * LEVERAGE
        quantidade = round(valor_nominal / sinal['preco_atual'], qty_precision)
        
        tp1 = round(sinal['alvos'][0], price_precision)
        sl = round(sinal['stop_loss'], price_precision)

        side = SIDE_BUY if sinal['direcao'] == "COMPRA" else SIDE_SELL
        side_contrario = SIDE_SELL if sinal['direcao'] == "COMPRA" else SIDE_BUY
        
        binance_client.futures_create_order(symbol=simbolo, side=side, type=FUTURE_ORDER_TYPE_MARKET, quantity=quantidade)
        binance_client.futures_create_order(symbol=simbolo, side=side_contrario, type=FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET, stopPrice=tp1, closePosition=True)
        binance_client.futures_create_order(symbol=simbolo, side=side_contrario, type=FUTURE_ORDER_TYPE_STOP_MARKET, stopPrice=sl, closePosition=True)
        
        sistema_winrate.atualizar_execucao(sinal['id'], True)
        return True
    except Exception as e:
        logger.error(f"Erro Binance: {e}")
        return False

# =========================
# DASHBOARD TEMPLATE (ORIGINAL)
# =========================
DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FAT PIG SIGNALS - Winrate</title>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        :root {
            --bg: #0a0a0a;
            --card: #151515;
            --amarelo-brasil: #ffdf00;
            --verde-win: #00ff88;
            --vermelho-loss: #ff4757;
            --azul-brasil: #002776;
        }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: var(--bg); color: white; margin: 0; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { text-align: center; padding: 40px 0; border-bottom: 3px solid var(--amarelo-brasil); margin-bottom: 30px; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .stat-card { background: var(--card); padding: 20px; border-radius: 15px; text-align: center; border: 1px solid rgba(255,255,255,0.1); }
        .stat-value { font-size: 1.8em; font-weight: bold; color: var(--amarelo-brasil); }
        .sinais-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
        .card-sinal { background: var(--card); padding: 20px; border-radius: 15px; border-left: 5px solid var(--amarelo-brasil); position: relative; }
        .badge-exec { position: absolute; top: 10px; right: 10px; font-size: 0.7em; padding: 5px 10px; border-radius: 10px; background: var(--azul-brasil); }
        .compra { border-left-color: var(--verde-win); }
        .venda { border-left-color: var(--vermelho-loss); }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🇧🇷 FAT PIG SIGNALS - BINANCE AUTO-TRADE</h1>
            <p>Monitoramento em Tempo Real e Execução Automática</p>
        </div>
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value">{{ stats.winrate_formatado }}</div>
                <div class="stat-label">WINRATE</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ stats.total_sinais }}</div>
                <div class="stat-label">TOTAL SINAIS</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ stats.profit_total_formatado }}</div>
                <div class="stat-label">PROFIT TOTAL</div>
            </div>
        </div>
        <h2>Últimos Sinais</h2>
        <div class="sinais-grid">
            {% for sinal in sinais %}
            <div class="card-sinal {{ sinal.direcao.lower() }}">
                {% if sinal.executado_binance %}
                <div class="badge-exec">✅ BINANCE</div>
                {% endif %}
                <h3>{{ sinal.simbolo }} - {{ sinal.direcao }}</h3>
                <p>Preço: ${{ sinal.preco_atual }}</p>
                <p>TP1: {{ sinal.alvos[0] }} | SL: {{ sinal.stop_loss }}</p>
                <small>{{ sinal.timestamp }}</small>
            </div>
            {% endfor %}
        </div>
    </div>
</body>
</html>
'''

# =========================
# ROTAS E LOGICA
# =========================
@app.route('/')
def dashboard():
    return render_template_string(
        DASHBOARD_TEMPLATE,
        sinais=sistema_winrate.get_historico(10)[::-1],
        stats=sistema_winrate.get_estatisticas()
    )

def buscar_preco_real(simbolo):
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={simbolo}", timeout=5).json()
        return float(res['price'])
    except: return 0.0

def enviar_telegram(sinal, exec_status):
    if not TELEGRAM_TOKEN: return
    status = "✅ EXECUTADO NA BINANCE" if exec_status else "⚠️ SINAL GERADO (SEM EXECUÇÃO)"
    msg = f"📢 *{sinal['simbolo']} - {sinal['direcao']}*\nPreço: {sinal['preco_atual']}\nTP1: {sinal['alvos'][0]}\nSL: {sinal['stop_loss']}\n\n🤖 {status}"
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})

def gerar_sinal(simbolo):
    preco = buscar_preco_real(simbolo)
    if preco == 0: return
    direcao = random.choice(["COMPRA", "VENDA"])
    sinal = {
        "id": f"{simbolo}{int(time.time())}", "simbolo": simbolo, "direcao": direcao,
        "preco_atual": preco, "entrada": preco, "alvos": [round(preco*1.01, 4) if direcao=="COMPRA" else round(preco*0.99, 4)],
        "stop_loss": round(preco*0.99, 4) if direcao=="COMPRA" else round(preco*1.01, 4),
        "timestamp": datetime.now().strftime("%H:%M:%S")
    }
    sistema_winrate.adicionar_sinal(sinal)
    sucesso = executar_trade_binance(sinal)
    enviar_telegram(sinal, sucesso)

def worker():
    simbolos = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    while True:
        for s in simbolos:
            if random.random() < 0.1: gerar_sinal(s)
            time.sleep(2)
        time.sleep(BOT_INTERVAL)

if __name__ == '__main__':
    threading.Thread(target=worker, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT)
