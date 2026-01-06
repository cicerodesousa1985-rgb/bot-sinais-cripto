import os
import time
import threading
import requests
import json
import logging
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template_string
from collections import deque
import random

# =========================
# CONFIGURAÇÃO
# =========================
app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configurações via Ambiente
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
BOT_INTERVAL = int(os.getenv("BOT_INTERVAL", "300"))  # 5 minutos
PORT = int(os.getenv("PORT", "10000"))

# Inicializar Exchange (Binance)
exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

# =========================
# ANÁLISE TÉCNICA REAL
# =========================

def calcular_rsi(series, period=14):
    """Calcula o RSI real usando pandas"""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calcular_macd(series, fast=12, slow=26, signal=9):
    """Calcula o MACD real usando pandas"""
    exp1 = series.ewm(span=fast, adjust=False).mean()
    exp2 = series.ewm(span=slow, adjust=False).mean()
    macd = exp1 - exp2
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    return macd, signal_line

def obter_dados_mercado(symbol, timeframe='1h', limit=100):
    """Busca dados OHLCV reais da exchange"""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        logger.error(f"Erro ao buscar dados para {symbol}: {e}")
        return None

# =========================
# SISTEMA DE WINRATE REAL
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
        self.lock = threading.Lock()

    def adicionar_sinal(self, sinal):
        with self.lock:
            sinal_completo = {
                **sinal,
                "resultado": None,
                "timestamp_fechamento": None,
                "profit": 0.0,
                "status": "ABERTO"
            }
            self.sinais.append(sinal_completo)
            self.estatisticas["total_sinais"] += 1
            self.atualizar_estatisticas()
            return sinal_completo

    def atualizar_resultado(self, sinal_id, resultado, profit):
        with self.lock:
            for sinal in self.sinais:
                if sinal["id"] == sinal_id and sinal["status"] == "ABERTO":
                    sinal["resultado"] = resultado
                    sinal["profit"] = profit
                    sinal["status"] = "FECHADO"
                    sinal["timestamp_fechamento"] = datetime.now().isoformat()
                    
                    if resultado == "WIN":
                        self.estatisticas["sinais_vencedores"] += 1
                    else:
                        self.estatisticas["sinais_perdedores"] += 1
                    
                    self.estatisticas["profit_total"] += profit
                    self.atualizar_estatisticas()
                    break

    def atualizar_estatisticas(self):
        total = self.estatisticas["sinais_vencedores"] + self.estatisticas["sinais_perdedores"]
        if total > 0:
            self.estatisticas["winrate"] = (self.estatisticas["sinais_vencedores"] / total) * 100
        
        hoje = datetime.now().date()
        sinais_hoje = [s for s in self.sinais if datetime.fromisoformat(s["timestamp"]).date() == hoje]
        self.estatisticas["sinais_hoje"] = len(sinais_hoje)
        
        sinais_fechados_hoje = [s for s in sinais_hoje if s["status"] == "FECHADO"]
        if sinais_fechados_hoje:
            wins_hoje = sum(1 for s in sinais_fechados_hoje if s["resultado"] == "WIN")
            self.estatisticas["winrate_hoje"] = (wins_hoje / len(sinais_fechados_hoje)) * 100
            
        self.estatisticas["ultima_atualizacao"] = datetime.now().strftime("%H:%M:%S")

    def get_estatisticas(self):
        return {
            **self.estatisticas,
            "winrate_formatado": f"{self.estatisticas['winrate']:.1f}%",
            "winrate_hoje_formatado": f"{self.estatisticas['winrate_hoje']:.1f}%",
            "profit_total_formatado": f"{self.estatisticas['profit_total']:+.2f}%",
            "total_fechados": self.estatisticas["sinais_vencedores"] + self.estatisticas["sinais_perdedores"],
            "sinais_em_aberto": sum(1 for s in self.sinais if s["status"] == "ABERTO")
        }

    def get_historico(self, limite=20):
        return list(self.sinais)[-limite:]

sistema_winrate = SistemaWinrate()

# =========================
# LÓGICA DE SINAIS REAIS
# =========================

def gerar_sinal_real(symbol):
    """Gera sinal baseado em indicadores reais"""
    df = obter_dados_mercado(symbol)
    if df is None or len(df) < 30:
        return None

    # Calcular indicadores
    df['rsi'] = calcular_rsi(df['close'])
    df['macd'], df['macd_signal'] = calcular_macd(df['close'])
    
    ultimo_rsi = df['rsi'].iloc[-1]
    ultimo_macd = df['macd'].iloc[-1]
    ultimo_signal = df['macd_signal'].iloc[-1]
    preco_atual = df['close'].iloc[-1]
    
    direcao = None
    motivo = ""
    
    # Estratégia: RSI + Cruzamento MACD
    if ultimo_rsi < 30:
        direcao = "COMPRA"
        motivo = f"RSI Sobrevendido ({ultimo_rsi:.1f})"
    elif ultimo_rsi > 70:
        direcao = "VENDA"
        motivo = f"RSI Sobrecomprado ({ultimo_rsi:.1f})"
    elif ultimo_macd > ultimo_signal and df['macd'].iloc[-2] <= df['macd_signal'].iloc[-2]:
        direcao = "COMPRA"
        motivo = "Cruzamento de Alta MACD"
    elif ultimo_macd < ultimo_signal and df['macd'].iloc[-2] >= df['macd_signal'].iloc[-2]:
        direcao = "VENDA"
        motivo = "Cruzamento de Baixa MACD"
        
    if not direcao:
        return None

    # Definir Alvos e Stop (Baseado em volatilidade simples)
    volatilidade = df['close'].pct_change().std()
    if direcao == "COMPRA":
        entrada = preco_atual
        stop_loss = preco_atual * (1 - (volatilidade * 2))
        alvos = [
            preco_atual * (1 + volatilidade * 1.5),
            preco_atual * (1 + volatilidade * 3),
            preco_atual * (1 + volatilidade * 5)
        ]
    else:
        entrada = preco_atual
        stop_loss = preco_atual * (1 + (volatilidade * 2))
        alvos = [
            preco_atual * (1 - volatilidade * 1.5),
            preco_atual * (1 - volatilidade * 3),
            preco_atual * (1 - volatilidade * 5)
        ]

    sinal = {
        "id": f"{symbol.replace('/', '')}_{int(time.time())}",
        "simbolo": symbol,
        "direcao": direcao,
        "preco_atual": round(preco_atual, 4),
        "entrada": round(entrada, 4),
        "alvos": [round(a, 4) for a in alvos],
        "stop_loss": round(stop_loss, 4),
        "confianca": 0.85 if "RSI" in motivo else 0.75,
        "motivo": motivo,
        "timestamp": datetime.now().isoformat(),
        "hora": datetime.now().strftime("%H:%M"),
        "lucro_potencial": f"{abs((alvos[0]/entrada - 1)*100):.1f}%"
    }
    
    sinal_completo = sistema_winrate.adicionar_sinal(sinal)
    
    # Iniciar monitoramento real do sinal
    threading.Thread(target=monitorar_sinal_real, args=(sinal_completo,), daemon=True).start()
    
    return sinal_completo

def monitorar_sinal_real(sinal):
    """Monitora o preço real para validar o sinal (Take Profit ou Stop Loss)"""
    symbol = sinal["simbolo"]
    id_sinal = sinal["id"]
    tp1 = sinal["alvos"][0]
    stop = sinal["stop_loss"]
    direcao = sinal["direcao"]
    
    logger.info(f"👀 Monitorando sinal {id_sinal} para {symbol}")
    
    # Monitorar por até 4 horas
    tempo_limite = datetime.now() + timedelta(hours=4)
    
    while datetime.now() < tempo_limite:
        try:
            ticker = exchange.fetch_ticker(symbol)
            preco_atual = ticker['last']
            
            if direcao == "COMPRA":
                if preco_atual >= tp1:
                    profit = ((tp1 / sinal["entrada"]) - 1) * 100
                    sistema_winrate.atualizar_resultado(id_sinal, "WIN", profit)
                    logger.info(f"✅ WIN: {symbol} atingiu TP1")
                    return
                elif preco_atual <= stop:
                    profit = ((stop / sinal["entrada"]) - 1) * 100
                    sistema_winrate.atualizar_resultado(id_sinal, "LOSS", profit)
                    logger.info(f"❌ LOSS: {symbol} atingiu Stop Loss")
                    return
            else: # VENDA
                if preco_atual <= tp1:
                    profit = (1 - (tp1 / sinal["entrada"])) * 100
                    sistema_winrate.atualizar_resultado(id_sinal, "WIN", profit)
                    logger.info(f"✅ WIN: {symbol} atingiu TP1")
                    return
                elif preco_atual >= stop:
                    profit = (1 - (stop / sinal["entrada"])) * 100
                    sistema_winrate.atualizar_resultado(id_sinal, "LOSS", profit)
                    logger.info(f"❌ LOSS: {symbol} atingiu Stop Loss")
                    return
                    
            time.sleep(30) # Verificar a cada 30 segundos
        except Exception as e:
            logger.error(f"Erro ao monitorar {symbol}: {e}")
            time.sleep(60)
            
    # Se expirar sem atingir TP ou SL
    try:
        ticker = exchange.fetch_ticker(symbol)
        preco_final = ticker['last']
        if direcao == "COMPRA":
            profit = ((preco_final / sinal["entrada"]) - 1) * 100
        else:
            profit = (1 - (preco_final / sinal["entrada"])) * 100
        
        resultado = "WIN" if profit > 0 else "LOSS"
        sistema_winrate.atualizar_resultado(id_sinal, resultado, profit)
        logger.info(f"⏱️ EXPIRADO: {symbol} fechado por tempo. Resultado: {resultado}")
    except:
        sistema_winrate.atualizar_resultado(id_sinal, "LOSS", -1.0)

# =========================
# TELEGRAM
# =========================

def enviar_telegram_sinal(sinal):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return False
    
    emoji = "🟢" if sinal["direcao"] == "COMPRA" else "🔴"
    mensagem = f"""
{emoji} *{sinal['direcao']} REAL* - {sinal['simbolo']}
💰 *Preço:* `${sinal['preco_atual']:,.2f}`
🎯 *Entrada:* `${sinal['entrada']:,.2f}`
📈 *Alvos:* 
  TP1: `${sinal['alvos'][0]:,.2f}`
  TP2: `${sinal['alvos'][1]:,.2f}`
  TP3: `${sinal['alvos'][2]:,.2f}`
🛑 *Stop:* `${sinal['stop_loss']:,.2f}`
💡 *Motivo:* {sinal['motivo']}
🏆 *Winrate Real:* {sistema_winrate.estatisticas['winrate']:.1f}%
    """
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": mensagem, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        logger.error(f"Erro Telegram: {e}")

# =========================
# DASHBOARD (Simplificado para o exemplo)
# =========================

DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Crypto Bot V2 - Real Analysis</title>
    <style>
        body { font-family: sans-serif; background: #121212; color: white; padding: 20px; }
        .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 20px; }
        .card { background: #1e1e1e; padding: 15px; border-radius: 8px; text-align: center; border: 1px solid #333; }
        .win { color: #00ff88; }
        .loss { color: #ff4757; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #333; }
        th { background: #252525; }
    </style>
</head>
<body>
    <h1>🚀 Crypto Signals Bot V2 (Real Data)</h1>
    <div class="stats">
        <div class="card"><h3>Winrate</h3><h2 class="win">{{ stats.winrate_formatado }}</h2></div>
        <div class="card"><h3>Sinais Hoje</h3><h2>{{ stats.sinais_hoje }}</h2></div>
        <div class="card"><h3>Profit Total</h3><h2 class="{{ 'win' if stats.profit_total >= 0 else 'loss' }}">{{ stats.profit_total_formatado }}</h2></div>
        <div class="card"><h3>Em Aberto</h3><h2>{{ stats.sinais_em_aberto }}</h2></div>
    </div>
    
    <h2>Últimos Sinais</h2>
    <table>
        <tr>
            <th>Par</th>
            <th>Direção</th>
            <th>Entrada</th>
            <th>Resultado</th>
            <th>Profit</th>
            <th>Status</th>
        </tr>
        {% for s in sinais %}
        <tr>
            <td>{{ s.simbolo }}</td>
            <td class="{{ 'win' if s.direcao == 'COMPRA' else 'loss' }}">{{ s.direcao }}</td>
            <td>${{ s.entrada }}</td>
            <td class="{{ 'win' if s.resultado == 'WIN' else 'loss' }}">{{ s.resultado or '-' }}</td>
            <td class="{{ 'win' if s.profit > 0 else 'loss' }}">{{ s.profit|round(2) }}%</td>
            <td>{{ s.status }}</td>
        </tr>
        {% endfor %}
    </table>
</body>
</html>
'''

@app.route('/')
def dashboard():
    return render_template_string(
        DASHBOARD_TEMPLATE,
        stats=sistema_winrate.get_estatisticas(),
        sinais=sistema_winrate.get_historico(20)[::-1]
    )

# =========================
# WORKER E MAIN
# =========================

def worker_principal():
    logger.info("🤖 Bot V2 Iniciado com Dados Reais")
    simbolos = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT"]
    
    while True:
        try:
            for symbol in simbolos:
                sinal = gerar_sinal_real(symbol)
                if sinal:
                    logger.info(f"📢 Novo sinal real gerado: {sinal['direcao']} {symbol}")
                    enviar_telegram_sinal(sinal)
                time.sleep(2)
            
            time.sleep(BOT_INTERVAL)
        except Exception as e:
            logger.error(f"Erro no worker: {e}")
            time.sleep(60)

if __name__ == '__main__':
    threading.Thread(target=worker_principal, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT)
