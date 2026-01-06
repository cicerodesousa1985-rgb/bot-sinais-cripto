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
BOT_INTERVAL = int(os.getenv("BOT_INTERVAL", "180")) # Reduzido para 3 min para mais sinais
PORT = int(os.getenv("PORT", "10000"))

exchange = ccxt.bybit({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})
DB_PATH = "bot_signals_v5.db"

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

def salvar_sinal_db(s):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO sinais (id, simbolo, direcao, entrada, tp1, stop, estrategia, motivo, resultado, profit, status, timestamp, timestamp_fechamento)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (s['id'], s['simbolo'], s['direcao'], s['entrada'], s['alvos'][0], s['stop_loss'], s['estrategia'], s['motivo'], s.get('resultado'), s.get('profit', 0.0), s['status'], s['timestamp'], s.get('timestamp_fechamento')))
    conn.commit()
    conn.close()

init_db()

# =========================
# INDICADORES TÉCNICOS AVANÇADOS
# =========================
def calcular_indicadores(df):
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss)))
    
    # Médias Móveis (Cruzamento)
    df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # Bandas de Bollinger
    df['sma20'] = df['close'].rolling(window=20).mean()
    df['std20'] = df['close'].rolling(window=20).std()
    df['upper_band'] = df['sma20'] + (df['std20'] * 2)
    df['lower_band'] = df['sma20'] - (df['std20'] * 2)
    
    # Volume (Média de Volume)
    df['vol_avg'] = df['volume'].rolling(window=20).mean()
    
    # ATR (Para Stop Loss Dinâmico)
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df['atr'] = true_range.rolling(14).mean()
    
    return df

# =========================
# MÚLTIPLAS ESTRATÉGIAS
# =========================

def analisar_estrategias(df, symbol):
    last = df.iloc[-1]
    prev = df.iloc[-2]
    preco = last['close']
    sinais = []

    # 1. ESTRATÉGIA: CRUZAMENTO DE MÉDIAS (TENDÊNCIA)
    if last['ema9'] > last['ema21'] and prev['ema9'] <= prev['ema21'] and preco > last['ema200']:
        sinais.append({"direcao": "COMPRA", "estrategia": "GOLDEN CROSS", "motivo": "Cruzamento EMA 9/21 (Alta)"})
    elif last['ema9'] < last['ema21'] and prev['ema9'] >= prev['ema21'] and preco < last['ema200']:
        sinais.append({"direcao": "VENDA", "estrategia": "DEATH CROSS", "motivo": "Cruzamento EMA 9/21 (Baixa)"})

    # 2. ESTRATÉGIA: REVERSÃO DE BANDAS + RSI (SCALPING)
    if last['close'] <= last['lower_band'] and last['rsi'] < 30:
        sinais.append({"direcao": "COMPRA", "estrategia": "BOLLINGER REVERSAL", "motivo": "Preço abaixo da Banda + RSI Sobrevendido"})
    elif last['close'] >= last['upper_band'] and last['rsi'] > 70:
        sinais.append({"direcao": "VENDA", "estrategia": "BOLLINGER REVERSAL", "motivo": "Preço acima da Banda + RSI Sobrecomprado"})

    # 3. ESTRATÉGIA: BREAKOUT DE VOLUME
    if last['volume'] > (last['vol_avg'] * 2):
        if last['close'] > prev['high'] and last['rsi'] > 50:
            sinais.append({"direcao": "COMPRA", "estrategia": "VOLUME BREAKOUT", "motivo": "Rompimento com Volume Alto"})
        elif last['close'] < prev['low'] and last['rsi'] < 50:
            sinais.append({"direcao": "VENDA", "estrategia": "VOLUME BREAKOUT", "motivo": "Queda com Volume Alto"})

    return sinais

# =========================
# GERADOR DE SINAIS V5
# =========================

def processar_sinais(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, '15m', limit=200) # Timeframe menor para mais sinais
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df = calcular_indicadores(df)
        
        oportunidades = analisar_estrategias(df, symbol)
        
        for op in oportunidades:
            # Evitar sinais duplicados para o mesmo par no mesmo minuto
            sinal_id = f"{symbol.replace('/', '')}_{int(time.time()) // 60}"
            
            # Verificar se já existe sinal recente no DB
            conn = sqlite3.connect(DB_PATH)
            check = conn.execute("SELECT id FROM sinais WHERE id=?", (sinal_id,)).fetchone()
            conn.close()
            if check: continue

            preco = df.iloc[-1]['close']
            atr = df.iloc[-1]['atr']
            
            # Alvos baseados em ATR (mais precisos)
            tp = preco + (atr * 2) if op['direcao'] == "COMPRA" else preco - (atr * 2)
            sl = preco - (atr * 1.5) if op['direcao'] == "COMPRA" else preco + (atr * 1.5)

            sinal = {
                "id": sinal_id, "simbolo": symbol, "direcao": op['direcao'], 
                "entrada": round(preco, 4), "alvos": [round(tp, 4)], "stop_loss": round(sl, 4),
                "estrategia": op['estrategia'], "motivo": op['motivo'],
                "timestamp": datetime.now().isoformat(), "status": "ABERTO"
            }
            
            salvar_sinal_db(sinal)
            threading.Thread(target=monitorar_sinal, args=(sinal,), daemon=True).start()
            notificar_telegram(sinal)
            
    except Exception as e:
        logger.error(f"Erro ao processar {symbol}: {e}")

def monitorar_sinal(sinal):
    symbol, id_sinal, tp, sl, direcao = sinal["simbolo"], sinal["id"], sinal["alvos"][0], sinal["stop_loss"], sinal["direcao"]
    for _ in range(240): # 2 horas de monitoramento
        try:
            p = exchange.fetch_ticker(symbol)['last']
            if (direcao == "COMPRA" and p >= tp) or (direcao == "VENDA" and p <= tp):
                finalizar_sinal(id_sinal, "WIN", abs((tp/sinal['entrada']-1)*100))
                return
            if (direcao == "COMPRA" and p <= sl) or (direcao == "VENDA" and p >= sl):
                finalizar_sinal(id_sinal, "LOSS", -abs((sl/sinal['entrada']-1)*100))
                return
            time.sleep(30)
        except: time.sleep(60)
    
    # Fechamento por tempo
    try:
        p = exchange.fetch_ticker(symbol)['last']
        profit = ((p/sinal['entrada']-1)*100) if direcao == "COMPRA" else (1-p/sinal['entrada'])*100
        finalizar_sinal(id_sinal, "WIN" if profit > 0 else "LOSS", profit)
    except: pass

def finalizar_sinal(sinal_id, resultado, profit):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE sinais SET resultado=?, profit=?, status='FECHADO', timestamp_fechamento=? WHERE id=?", 
                (resultado, profit, datetime.now().isoformat(), sinal_id))
    conn.commit()
    conn.close()
    
    if TELEGRAM_TOKEN and CHAT_ID:
        emoji = "💰" if resultado == "WIN" else "📉"
        msg = f"{emoji} *SINAL ENCERRADO*\nID: `{sinal_id}`\nResultado: *{resultado}*\nProfit: `{profit:.2f}%`"
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})

def notificar_telegram(s):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    emoji = "🚀" if s['direcao'] == "COMPRA" else "📉"
    msg = f"{emoji} *NOVO SINAL [{s['estrategia']}]*\nPar: `{s['simbolo']}`\nDireção: *{s['direcao']}*\nEntrada: `{s['entrada']}`\nAlvo: `{s['alvos'][0]}`\nStop: `{s['stop_loss']}`\n💡 {s['motivo']}"
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})

# =========================
# DASHBOARD V5
# =========================

DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Fat Pig Signals V5 - Multi-Strategy</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --primary: #f5a623; --bg: #0b0e11; --card: #1e2329; --text: #eaecef; --success: #0ecb81; --danger: #f6465d; }
        body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); margin: 0; }
        .header { background: #000; padding: 15px 5%; display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid var(--primary); }
        .container { max-width: 1400px; margin: 20px auto; padding: 0 20px; }
        .stats-bar { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px; margin-bottom: 25px; }
        .card { background: var(--card); padding: 20px; border-radius: 10px; text-align: center; border: 1px solid #2b3139; }
        .signals-grid { display: grid; grid-template-columns: 1fr; gap: 20px; }
        .table-container { background: var(--card); border-radius: 12px; overflow: hidden; border: 1px solid #2b3139; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 15px; text-align: left; border-bottom: 1px solid #2b3139; font-size: 13px; }
        .badge-strat { background: var(--primary); color: #000; padding: 3px 8px; border-radius: 4px; font-size: 10px; font-weight: bold; }
        .buy { color: var(--success); } .sell { color: var(--danger); }
    </style>
</head>
<body>
    <div class="header">
        <div style="font-weight: 900; color: var(--primary); font-size: 22px;">FAT PIG <span style="color:#fff">V5 MULTI-STRAT</span></div>
        <div style="font-size: 12px; color: var(--success);"><i class="fas fa-bolt"></i> SCANNING MARKET...</div>
    </div>
    <div class="container">
        <div class="stats-bar">
            <div class="card"><div style="color:var(--primary); font-size:24px; font-weight:800;">{{ stats.winrate }}%</div><div style="font-size:11px;">WINRATE</div></div>
            <div class="card"><div style="font-size:24px; font-weight:800;">{{ stats.total }}</div><div style="font-size:11px;">SINAIS TOTAIS</div></div>
            <div class="card"><div style="font-size:24px; font-weight:800; color:var(--success)">{{ stats.profit }}%</div><div style="font-size:11px;">PROFIT ACUMULADO</div></div>
            <div class="card"><div style="font-size:24px; font-weight:800;">{{ stats.abertos }}</div><div style="font-size:11px;">EM ABERTO</div></div>
        </div>
        <div class="table-container">
            <div style="padding:15px; background:#161a1e; font-weight:bold; display:flex; justify-content:space-between;">
                <span><i class="fas fa-satellite-dish"></i> MONITORAMENTO MULTI-ESTRATÉGIA</span>
                <span style="font-size:11px; color:#848e9c;">Timeframe: 15m / 1h</span>
            </div>
            <table>
                <thead><tr><th>Par</th><th>Estratégia</th><th>Direção</th><th>Entrada</th><th>Resultado</th><th>Profit</th><th>Motivo</th></tr></thead>
                <tbody>
                    {% for s in sinais %}
                    <tr>
                        <td><b>{{ s.simbolo }}</b></td>
                        <td><span class="badge-strat">{{ s.estrategia }}</span></td>
                        <td class="{{ 'buy' if s.direcao == 'COMPRA' else 'sell' }}"><b>{{ s.direcao }}</b></td>
                        <td>${{ s.entrada }}</td>
                        <td>{{ s.resultado or 'ABERTO' }}</td>
                        <td style="color:{{ '#0ecb81' if s.profit > 0 else '#f6465d' if s.profit < 0 else '#fff' }}">{{ s.profit|round(2) }}%</td>
                        <td style="font-size:11px; color:#848e9c;">{{ s.motivo }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
'''

@app.route('/')
def dashboard():
    conn = sqlite3.connect(DB_PATH)
    sinais = pd.read_sql_query("SELECT * FROM sinais ORDER BY timestamp DESC LIMIT 30", conn).to_dict('records')
    stats_raw = conn.execute("SELECT COUNT(*), SUM(CASE WHEN resultado='WIN' THEN 1 ELSE 0 END), SUM(profit) FROM sinais WHERE status='FECHADO'").fetchone()
    abertos = conn.execute("SELECT COUNT(*) FROM sinais WHERE status='ABERTO'").fetchone()[0]
    conn.close()
    
    total = stats_raw[0] or 0
    wins = stats_raw[1] or 0
    profit = stats_raw[2] or 0.0
    
    stats = {"total": total, "winrate": round((wins/total*100),1) if total > 0 else 0, "profit": round(profit,2), "abertos": abertos}
    return render_template_string(DASHBOARD_TEMPLATE, stats=stats, sinais=sinais)

def worker():
    simbolos = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT", "DOT/USDT", "MATIC/USDT", "LINK/USDT"]
    while True:
        for s in simbolos:
            processar_sinais(s)
            time.sleep(3)
        time.sleep(BOT_INTERVAL)

if __name__ == '__main__':
    threading.Thread(target=worker, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT)
