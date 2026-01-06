import os
import time
import threading
import requests
import json
import logging
import pandas as pd
import numpy as np
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template_string

# =========================
# CONFIGURAÇÃO E LOGGING
# =========================
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
BOT_INTERVAL = int(os.getenv("BOT_INTERVAL", "120"))
PORT = int(os.getenv("PORT", "10000"))

DB_PATH = "bot_signals_v5.db"
monitor_precos = {}

# =========================
# COLETA DE DADOS VIA API PÚBLICA
# =========================

def obter_dados_publicos(symbol):
    """Busca dados OHLCV via API Pública da Binance (sem CCXT/Auth)"""
    try:
        # Formatar símbolo para Binance (ex: BTCUSDT)
        clean_symbol = symbol.replace("/", "").replace("-", "")
        url = f"https://api.binance.com/api/v3/klines?symbol={clean_symbol}&interval=15m&limit=100"
        
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume', 
                'close_time', 'quote_asset_volume', 'number_of_trades', 
                'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
            ])
            df['close'] = df['close'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            df['volume'] = df['volume'].astype(float)
            return df
            
        # Fallback para CryptoCompare se a Binance falhar
        logger.warning(f"Binance falhou para {symbol}, tentando CryptoCompare...")
        fsym = symbol.split("/")[0]
        url_cc = f"https://min-api.cryptocompare.com/data/v2/histominute?fsym={fsym}&tsym=USDT&limit=100"
        res_cc = requests.get(url_cc, timeout=10)
        if res_cc.status_code == 200:
            data_cc = res_cc.json()['Data']['Data']
            df_cc = pd.DataFrame(data_cc)
            df_cc = df_cc.rename(columns={'time': 'timestamp'})
            return df_cc
            
    except Exception as e:
        logger.error(f"Erro ao buscar dados públicos para {symbol}: {e}")
    return None

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
# INDICADORES E ESTRATÉGIAS
# =========================
def calcular_indicadores(df):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss)))
    df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
    return df

def analisar_estrategias(df):
    last = df.iloc[-1]
    prev = df.iloc[-2]
    sinais = []
    
    # Cruzamento EMA
    if last['ema9'] > last['ema21'] and prev['ema9'] <= prev['ema21']:
        sinais.append({"direcao": "COMPRA", "estrategia": "PUBLIC EMA", "motivo": "Cruzamento de Alta"})
    elif last['ema9'] < last['ema21'] and prev['ema9'] >= prev['ema21']:
        sinais.append({"direcao": "VENDA", "estrategia": "PUBLIC EMA", "motivo": "Cruzamento de Baixa"})
        
    # RSI Sensível
    if last['rsi'] < 38:
        sinais.append({"direcao": "COMPRA", "estrategia": "PUBLIC RSI", "motivo": f"RSI Baixo ({last['rsi']:.1f})"})
    elif last['rsi'] > 62:
        sinais.append({"direcao": "VENDA", "estrategia": "PUBLIC RSI", "motivo": f"RSI Alto ({last['rsi']:.1f})"})
        
    return sinais

# =========================
# PROCESSAMENTO
# =========================
def processar_sinais(symbol):
    global monitor_precos
    df = obter_dados_publicos(symbol)
    if df is None:
        monitor_precos[symbol] = {"preco": 0, "time": datetime.now().strftime("%H:%M:%S"), "status": "ERRO API"}
        return

    df = calcular_indicadores(df)
    preco_atual = df.iloc[-1]['close']
    monitor_precos[symbol] = {"preco": preco_atual, "time": datetime.now().strftime("%H:%M:%S"), "status": "ONLINE (PUBLIC)"}
    
    oportunidades = analisar_estrategias(df)
    for op in oportunidades:
        sinal_id = f"{symbol.replace('/', '')}_{int(time.time()) // 300}"
        
        conn = sqlite3.connect(DB_PATH)
        check = conn.execute("SELECT id FROM sinais WHERE id=?", (sinal_id,)).fetchone()
        conn.close()
        if check: continue

        tp = preco_atual * 1.015 if op['direcao'] == "COMPRA" else preco_atual * 0.985
        sl = preco_atual * 0.99 if op['direcao'] == "COMPRA" else preco_atual * 1.01

        sinal = {
            "id": sinal_id, "simbolo": symbol, "direcao": op['direcao'], 
            "entrada": round(preco_atual, 4), "alvos": [round(tp, 4)], "stop_loss": round(sl, 4),
            "estrategia": op['estrategia'], "motivo": op['motivo'],
            "timestamp": datetime.now().isoformat(), "status": "ABERTO"
        }
        
        # Salvar e Notificar
        conn = sqlite3.connect(DB_PATH)
        conn.execute('''INSERT INTO sinais (id, simbolo, direcao, entrada, tp1, stop, estrategia, motivo, status, timestamp) 
                        VALUES (?,?,?,?,?,?,?,?,?,?)''', 
                     (sinal['id'], sinal['simbolo'], sinal['direcao'], sinal['entrada'], sinal['alvos'][0], sinal['stop_loss'], sinal['estrategia'], sinal['motivo'], sinal['status'], sinal['timestamp']))
        conn.commit()
        conn.close()
        
        if TELEGRAM_TOKEN and CHAT_ID:
            msg = f"📢 *SINAL PÚBLICO [{sinal['estrategia']}]*\nPar: `{symbol}`\nDireção: *{sinal['direcao']}*\nEntrada: `{sinal['entrada']}`"
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})

# =========================
# DASHBOARD V5.2
# =========================
DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Fat Pig Signals V5.2 - Public API</title>
    <style>
        :root { --primary: #f5a623; --bg: #0b0e11; --card: #1e2329; --text: #eaecef; --success: #0ecb81; --danger: #f6465d; }
        body { font-family: sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 20px; }
        .monitor { background: #000; padding: 15px; border-radius: 8px; margin-bottom: 20px; font-family: monospace; border-left: 5px solid var(--primary); }
        .card { background: var(--card); padding: 20px; border-radius: 10px; border: 1px solid #333; margin-bottom: 20px; }
        table { width: 100%; border-collapse: collapse; background: var(--card); border-radius: 10px; overflow: hidden; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #333; }
        .buy { color: var(--success); } .sell { color: var(--danger); }
    </style>
</head>
<body>
    <h2 style="color: var(--primary)">🐷 FAT PIG SIGNALS V5.2 - PUBLIC API MODE</h2>
    
    <div class="monitor">
        <strong>📡 MONITOR DE PREÇOS (API PÚBLICA):</strong><br>
        {% for sym, data in monitor %}
            [{{ data.time }}] {{ sym }}: <span style="color:var(--primary)">${{ data.preco }}</span> | {{ data.status }}<br>
        {% endfor %}
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
    conn.close()
    return render_template_string(DASHBOARD_TEMPLATE, sinais=sinais, monitor=monitor_precos.items())

def worker():
    simbolos = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT"]
    while True:
        for s in simbolos:
            processar_sinais(s)
            time.sleep(3)
        time.sleep(BOT_INTERVAL)

if __name__ == '__main__':
    threading.Thread(target=worker, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT)
