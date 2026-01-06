import os
import time
import threading
import requests
import json
import logging
import ccxt
import pandas as pd
import numpy as np
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template_string
from collections import deque

# =========================
# CONFIGURAÇÃO E LOGGING
# =========================
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
BOT_INTERVAL = int(os.getenv("BOT_INTERVAL", "120")) # 2 minutos
PORT = int(os.getenv("PORT", "10000"))

# Troca para Gate.io (Excelente compatibilidade com Render/Cloud)
exchange = ccxt.gateio({'enableRateLimit': True})
DB_PATH = "bot_signals_v5.db"

# Cache global para monitoramento no Dashboard
monitor_precos = {}

# =========================
# BANCO DE DADOS
# =========================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sinais (
            id TEXT PRIMARY KEY, simbolo TEXT, direcao TEXT, entrada REAL, tp1 REAL, stop REAL, 
            estrategia TEXT, motivo TEXT, resultado TEXT, profit REAL, status TEXT, 
            timestamp DATETIME, timestamp_fechamento DATETIME
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# =========================
# INDICADORES TÉCNICOS
# =========================
def calcular_indicadores(df):
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss)))
    
    # Médias Móveis
    df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
    
    # Bandas de Bollinger
    df['sma20'] = df['close'].rolling(window=20).mean()
    df['std20'] = df['close'].rolling(window=20).std()
    df['upper_band'] = df['sma20'] + (df['std20'] * 2)
    df['lower_band'] = df['sma20'] - (df['std20'] * 2)
    
    return df

# =========================
# ESTRATÉGIAS MAIS SENSÍVEIS
# =========================
def analisar_estrategias(df, symbol):
    last = df.iloc[-1]
    prev = df.iloc[-2]
    preco = last['close']
    sinais = []

    # 1. Cruzamento EMA (Mais sensível)
    if last['ema9'] > last['ema21'] and prev['ema9'] <= prev['ema21']:
        sinais.append({"direcao": "COMPRA", "estrategia": "EMA CROSS", "motivo": "Cruzamento de Alta EMA 9/21"})
    elif last['ema9'] < last['ema21'] and prev['ema9'] >= prev['ema21']:
        sinais.append({"direcao": "VENDA", "estrategia": "EMA CROSS", "motivo": "Cruzamento de Baixa EMA 9/21"})

    # 2. RSI Reversal (Gatilhos 35/65 em vez de 30/70 para mais sinais)
    if last['rsi'] < 35:
        sinais.append({"direcao": "COMPRA", "estrategia": "RSI SCALPER", "motivo": f"RSI Sobrevendido ({last['rsi']:.1f})"})
    elif last['rsi'] > 65:
        sinais.append({"direcao": "VENDA", "estrategia": "RSI SCALPER", "motivo": f"RSI Sobrecomprado ({last['rsi']:.1f})"})

    return sinais

# =========================
# PROCESSAMENTO
# =========================
def processar_sinais(symbol):
    global monitor_precos
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, '15m', limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df = calcular_indicadores(df)
        
        preco_atual = df.iloc[-1]['close']
        monitor_precos[symbol] = {"preco": preco_atual, "time": datetime.now().strftime("%H:%M:%S"), "status": "OK"}
        
        oportunidades = analisar_estrategias(df, symbol)
        
        for op in oportunidades:
            sinal_id = f"{symbol.replace('/', '')}_{int(time.time()) // 300}" # 1 sinal a cada 5 min por par
            
            conn = sqlite3.connect(DB_PATH)
            check = conn.execute("SELECT id FROM sinais WHERE id=?", (sinal_id,)).fetchone()
            conn.close()
            if check: continue

            # Alvos fixos de 1.5% para teste rápido
            tp = preco_atual * 1.015 if op['direcao'] == "COMPRA" else preco_atual * 0.985
            sl = preco_atual * 0.99 if op['direcao'] == "COMPRA" else preco_atual * 1.01

            sinal = {
                "id": sinal_id, "simbolo": symbol, "direcao": op['direcao'], 
                "entrada": round(preco_atual, 4), "alvos": [round(tp, 4)], "stop_loss": round(sl, 4),
                "estrategia": op['estrategia'], "motivo": op['motivo'],
                "timestamp": datetime.now().isoformat(), "status": "ABERTO"
            }
            
            salvar_sinal_db(sinal)
            threading.Thread(target=monitorar_sinal, args=(sinal,), daemon=True).start()
            notificar_telegram(sinal)
            
    except Exception as e:
        logger.error(f"Erro em {symbol}: {e}")
        monitor_precos[symbol] = {"preco": 0, "time": datetime.now().strftime("%H:%M:%S"), "status": f"ERRO: {str(e)[:20]}"}

def monitorar_sinal(sinal):
    symbol, id_sinal, tp, sl, direcao = sinal["simbolo"], sinal["id"], sinal["alvos"][0], sinal["stop_loss"], sinal["direcao"]
    for _ in range(120): # 1 hora
        try:
            p = exchange.fetch_ticker(symbol)['last']
            if (direcao == "COMPRA" and p >= tp) or (direcao == "VENDA" and p <= tp):
                finalizar_sinal(id_sinal, "WIN", 1.5)
                return
            if (direcao == "COMPRA" and p <= sl) or (direcao == "VENDA" and p >= sl):
                finalizar_sinal(id_sinal, "LOSS", -1.0)
                return
            time.sleep(30)
        except: time.sleep(60)

def finalizar_sinal(sinal_id, resultado, profit):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE sinais SET resultado=?, profit=?, status='FECHADO', timestamp_fechamento=? WHERE id=?", 
                (resultado, profit, datetime.now().isoformat(), sinal_id))
    conn.commit()
    conn.close()

def notificar_telegram(s):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    msg = f"🚀 *NOVO SINAL [{s['estrategia']}]*\nPar: `{s['simbolo']}`\nDireção: *{s['direcao']}*\nEntrada: `{s['entrada']}`\n💡 {s['motivo']}"
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

# =========================
# DASHBOARD V5.1
# =========================
DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Fat Pig Signals V5.1 - Debug Mode</title>
    <style>
        :root { --primary: #f5a623; --bg: #0b0e11; --card: #1e2329; --text: #eaecef; --success: #0ecb81; --danger: #f6465d; }
        body { font-family: sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 20px; }
        .monitor { background: #000; padding: 10px; border-radius: 5px; margin-bottom: 20px; font-family: monospace; font-size: 12px; border-left: 4px solid var(--primary); }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 20px; }
        .card { background: var(--card); padding: 15px; border-radius: 8px; text-align: center; border: 1px solid #333; }
        table { width: 100%; border-collapse: collapse; background: var(--card); border-radius: 10px; overflow: hidden; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #333; }
        .buy { color: var(--success); } .sell { color: var(--danger); }
    </style>
</head>
<body>
    <h2 style="color: var(--primary)">🐷 FAT PIG SIGNALS V5.1 - LIVE MONITOR</h2>
    
    <div class="monitor">
        <strong>📡 STATUS DA API (GATE.IO):</strong><br>
        {% for sym, data in monitor %}
            [{{ data.time }}] {{ sym }}: ${{ data.preco }} | Status: {{ data.status }}<br>
        {% endfor %}
    </div>

    <div class="stats">
        <div class="card"><h3>Winrate</h3><h2 style="color:var(--primary)">{{ stats.winrate }}%</h2></div>
        <div class="card"><h3>Sinais</h3><h2>{{ stats.total }}</h2></div>
        <div class="card"><h3>Abertos</h3><h2>{{ stats.abertos }}</h2></div>
    </div>

    <table>
        <thead><tr><th>Par</th><th>Estratégia</th><th>Direção</th><th>Entrada</th><th>Status</th></tr></thead>
        <tbody>
            {% for s in sinais %}
            <tr>
                <td><b>{{ s.simbolo }}</b></td>
                <td>{{ s.estrategia }}</td>
                <td class="{{ 'buy' if s.direcao == 'COMPRA' else 'sell' }}"><b>{{ s.direcao }}</b></td>
                <td>${{ s.entrada }}</td>
                <td>{{ s.status }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</body>
</html>
'''

@app.route('/')
def dashboard():
    conn = sqlite3.connect(DB_PATH)
    sinais = pd.read_sql_query("SELECT * FROM sinais ORDER BY timestamp DESC LIMIT 20", conn).to_dict('records')
    stats_raw = conn.execute("SELECT COUNT(*), SUM(CASE WHEN resultado='WIN' THEN 1 ELSE 0 END) FROM sinais WHERE status='FECHADO'").fetchone()
    abertos = conn.execute("SELECT COUNT(*) FROM sinais WHERE status='ABERTO'").fetchone()[0]
    conn.close()
    total = stats_raw[0] or 0
    wins = stats_raw[1] or 0
    stats = {"total": total, "winrate": round((wins/total*100),1) if total > 0 else 0, "abertos": abertos}
    return render_template_string(DASHBOARD_TEMPLATE, stats=stats, sinais=sinais, monitor=monitor_precos.items())

def worker():
    simbolos = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"]
    while True:
        for s in simbolos:
            processar_sinais(s)
            time.sleep(2)
        time.sleep(BOT_INTERVAL)

if __name__ == '__main__':
    threading.Thread(target=worker, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT)
