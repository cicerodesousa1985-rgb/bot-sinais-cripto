
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
BOT_INTERVAL = 60  # Reduzido para 1 minuto para mais sinais
PORT = int(os.getenv("PORT", "10000"))

LEVERAGE = 10
MARGIN_TYPE = "ISOLATED"

try:
    binance_client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)
    logger.info("✅ Conectado à Binance")
except Exception as e:
    logger.error(f"❌ Erro Binance: {e}")
    binance_client = None

# =========================
# SISTEMA DE WINRATE
# =========================
class SistemaWinrate:
    def __init__(self):
        self.sinais = deque(maxlen=100)
        self.estatisticas = {"total_sinais": 0, "sinais_vencedores": 0, "sinais_perdedores": 0, "winrate": 0.0, "profit_total": 0.0, "ultima_atualizacao": None}
    
    def adicionar_sinal(self, sinal):
        sinal['executado_binance'] = False
        self.sinais.append(sinal)
        self.estatisticas["total_sinais"] += 1
        self.estatisticas["ultima_atualizacao"] = datetime.now().strftime("%H:%M:%S")
        return sinal

    def atualizar_execucao(self, sinal_id, status):
        for s in self.sinais:
            if s['id'] == sinal_id:
                s['executado_binance'] = status
                break

    def get_estatisticas(self):
        total = self.estatisticas["sinais_vencedores"] + self.estatisticas["sinais_perdedores"]
        winrate = (self.estatisticas["sinais_vencedores"] / total * 100) if total > 0 else 0
        return {**self.estatisticas, "winrate_formatado": f"{winrate:.1f}%"}

sistema_winrate = SistemaWinrate()

# =========================
# EXECUÇÃO DINÂMICA BINANCE
# =========================
def executar_trade_binance(sinal):
    if not binance_client: return False
    simbolo = sinal['simbolo']
    try:
        # 1. Configurar Margem e Alavancagem
        try: binance_client.futures_change_margin_type(symbol=simbolo, marginType=MARGIN_TYPE)
        except: pass
        binance_client.futures_change_leverage(symbol=simbolo, leverage=LEVERAGE)

        # 2. Buscar Lote Mínimo e Precisão
        info = binance_client.futures_exchange_info()
        s_info = next(i for i in info['symbols'] if i['symbol'] == simbolo)
        
        # Filtro de quantidade mínima (LOT_SIZE)
        lot_filter = next(f for f in s_info['filters'] if f['filterType'] == 'LOT_SIZE')
        min_qty = float(lot_filter['minQty'])
        qty_precision = s_info['quantityPrecision']
        
        # Filtro de valor nominal mínimo (MIN_NOTIONAL)
        min_notional = 5.1 # Padrão Binance Futures é 5 USDT, usamos 5.1 para garantir
        for f in s_info['filters']:
            if f['filterType'] == 'MIN_NOTIONAL':
                min_notional = float(f['notional']) if 'notional' in f else 5.1

        # 3. Calcular Quantidade Mínima Real
        # Quantidade = Valor Nominal / Preço
        quantidade = max(min_qty, round(min_notional / sinal['preco_atual'], qty_precision))
        
        # Garantir que a quantidade respeite o stepSize
        step_size = float(lot_filter['stepSize'])
        quantidade = round(quantidade // step_size * step_size, qty_precision)

        # 4. Executar Ordens
        side = SIDE_BUY if sinal['direcao'] == "COMPRA" else SIDE_SELL
        side_contrario = SIDE_SELL if sinal['direcao'] == "COMPRA" else SIDE_BUY
        
        # Entrada a Mercado
        binance_client.futures_create_order(symbol=simbolo, side=side, type=FUTURE_ORDER_TYPE_MARKET, quantity=quantidade)
        
        # TP e SL (Encerramento de Posição)
        price_precision = s_info['pricePrecision']
        tp = round(sinal['alvos'][0], price_precision)
        sl = round(sinal['stop_loss'], price_precision)

        binance_client.futures_create_order(symbol=simbolo, side=side_contrario, type=FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET, stopPrice=tp, closePosition=True)
        binance_client.futures_create_order(symbol=simbolo, side=side_contrario, type=FUTURE_ORDER_TYPE_STOP_MARKET, stopPrice=sl, closePosition=True)
        
        sistema_winrate.atualizar_execucao(sinal['id'], True)
        return True
    except Exception as e:
        logger.error(f"Erro na execução de {simbolo}: {e}")
        return False

# =========================
# LÓGICA DE SINAIS (AGRESSIVA)
# =========================
PARES = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "MATICUSDT", "LINKUSDT", "AVAXUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT", "SHIBUSDT", "TRXUSDT", "NEARUSDT"]

def gerar_sinal(simbolo):
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={simbolo}", timeout=5).json()
        preco = float(res['price'])
        
        # Estratégia Agressiva: Simula análise técnica rápida
        # Em um bot real, aqui entraria sua lógica de RSI/MACD
        direcao = random.choice(["COMPRA", "VENDA"])
        
        sinal = {
            "id": f"{simbolo}{int(time.time())}",
            "simbolo": simbolo,
            "direcao": direcao,
            "preco_atual": preco,
            "entrada": preco,
            "alvos": [round(preco*1.005, 4) if direcao=="COMPRA" else round(preco*0.995, 4)], # TP Curto para banca pequena
            "stop_loss": round(preco*0.99, 4) if direcao=="COMPRA" else round(preco*1.01, 4),
            "timestamp": datetime.now().strftime("%H:%M:%S")
        }
        
        sistema_winrate.adicionar_sinal(sinal)
        sucesso = executar_trade_binance(sinal)
        
        if TELEGRAM_TOKEN:
            status = "✅ EXECUTADO" if sucesso else "❌ SALDO/ERRO"
            msg = f"🚀 *{simbolo} - {direcao}*\n💰 Preço: {preco}\n🎯 TP1: {sinal['alvos'][0]}\n🛑 SL: {sinal['stop_loss']}\n🤖 Status: {status}"
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

def worker():
    logger.info("🤖 Bot Agressivo Iniciado")
    while True:
        # Tenta gerar sinais para 3 pares aleatórios da lista a cada ciclo
        selecionados = random.sample(PARES, 3)
        for s in selecionados:
            gerar_sinal(s)
            time.sleep(5)
        time.sleep(BOT_INTERVAL)

# =========================
# DASHBOARD
# =========================
@app.route('/')
def index():
    sinais = list(sistema_winrate.sinais)[::-1]
    stats = sistema_winrate.get_estatisticas()
    return render_template_string('''
    <html><head><title>FAT PIG AGRESSIVO</title>
    <style>
        body { background: #0a0a0a; color: white; font-family: sans-serif; text-align: center; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px; padding: 20px; }
        .card { background: #151515; padding: 15px; border-radius: 10px; border-left: 5px solid #ffdf00; }
        .exec { color: #00ff88; font-weight: bold; }
    </style></head><body>
    <h1>🇧🇷 FAT PIG - MODO AGRESSIVO</h1>
    <p>Winrate: {{stats.winrate_formatado}} | Sinais: {{stats.total_sinais}}</p>
    <div class="grid">
        {% for s in sinais %}
        <div class="card">
            <h3>{{s.simbolo}} - {{s.direcao}}</h3>
            <p>Preço: {{s.preco_atual}}</p>
            {% if s.executado_binance %}<p class="exec">✅ EXECUTADO NA BINANCE</p>{% endif %}
            <small>{{s.timestamp}}</small>
        </div>
        {% endfor %}
    </div>
    </body></html>''', sinais=sinais, stats=stats)

if __name__ == '__main__':
    threading.Thread(target=worker, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT)
