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
# CONFIGURAÇÃO ELITE
# =========================
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
BOT_INTERVAL = int(os.getenv("BOT_INTERVAL", "180"))
PORT = int(os.getenv("PORT", "10000"))

DB_PATH = "bot_signals_v6.db"
monitor_precos = {}

# =========================
# BANCO DE DADOS PRO
# =========================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sinais (
            id TEXT PRIMARY KEY, simbolo TEXT, direcao TEXT, entrada REAL, tp1 REAL, stop REAL, 
            confianca REAL, rr_ratio REAL, estrategia TEXT, motivo TEXT, resultado TEXT, 
            profit REAL, status TEXT, timestamp DATETIME
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# =========================
# MOTOR DE ANÁLISE ELITE
# =========================

def fetch_public_data(symbol):
    try:
        clean_symbol = symbol.replace("/", "").replace("-", "")
        url = f"https://api.binance.com/api/v3/klines?symbol={clean_symbol}&interval=1h&limit=100"
        res = requests.get(url, timeout=10).json()
        df = pd.DataFrame(res, columns=['ts','o','h','l','c','v','ct','qv','nt','tb','tq','i'])
        df[['h','l','c','v']] = df[['h','l','c','v']].astype(float)
        return df
    except: return None

def calcular_indicadores_elite(df):
    # RSI
    delta = df['c'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss)))
    
    # EMA Tendência
    df['ema20'] = df['c'].ewm(span=20, adjust=False).mean()
    df['ema50'] = df['c'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['c'].ewm(span=200, adjust=False).mean()
    
    # ATR para Alvos
    tr = pd.concat([df['h']-df['l'], abs(df['h']-df['c'].shift()), abs(df['l']-df['c'].shift())], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    
    return df

def gerar_sinal_elite(symbol):
    global monitor_precos
    df = fetch_public_data(symbol)
    if df is None: return
    
    df = calcular_indicadores_elite(df)
    last = df.iloc[-1]
    prev = df.iloc[-2]
    preco = last['c']
    monitor_precos[symbol] = {"p": preco, "t": datetime.now().strftime("%H:%M")}

    direcao = None
    confianca = 0
    motivo = ""

    # ESTRATÉGIA 1: CONFLUÊNCIA DE TENDÊNCIA (EMA + RSI)
    if preco > last['ema50'] and last['ema20'] > last['ema50'] and last['rsi'] < 45:
        direcao = "COMPRA"
        confianca = 85
        motivo = "Tendência de Alta + RSI em Recuo"
    elif preco < last['ema50'] and last['ema20'] < last['ema50'] and last['rsi'] > 55:
        direcao = "VENDA"
        confianca = 82
        motivo = "Tendência de Baixa + RSI em Recuperação"

    if not direcao: return

    # Cálculo de Alvos Profissionais (RR 1:2)
    atr = last['atr']
    tp = preco + (atr * 2.5) if direcao == "COMPRA" else preco - (atr * 2.5)
    sl = preco - (atr * 1.2) if direcao == "COMPRA" else preco + (atr * 1.2)
    rr = abs((tp-preco)/(preco-sl))

    sinal = {
        "id": f"{symbol.replace('/','')}_{int(time.time())}",
        "simbolo": symbol, "direcao": direcao, "entrada": round(preco, 4),
        "tp1": round(tp, 4), "stop": round(sl, 4), "confianca": confianca,
        "rr_ratio": round(rr, 2), "estrategia": "ELITE CONFLUENCE",
        "motivo": motivo, "status": "ABERTO", "timestamp": datetime.now().isoformat()
    }

    # Persistência e Telegram
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO sinais VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", 
                (sinal['id'], sinal['simbolo'], sinal['direcao'], sinal['entrada'], sinal['tp1'], sinal['stop'], 
                 sinal['confianca'], sinal['rr_ratio'], sinal['estrategia'], sinal['motivo'], None, 0.0, sinal['status'], sinal['timestamp']))
    conn.commit()
    conn.close()
    
    enviar_telegram_elite(sinal)

def enviar_telegram_elite(s):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    emoji = "💎 *ELITE SIGNAL*" if s['direcao'] == "COMPRA" else "🔥 *ELITE SIGNAL*"
    msg = f"""
{emoji}
━━━━━━━━━━━━━━
🪙 *PAR:* `{s['simbolo']}`
📈 *DIREÇÃO:* `{s['direcao']}`
💰 *ENTRADA:* `{s['entrada']}`
━━━━━━━━━━━━━━
🎯 *ALVO:* `{s['tp1']}`
🛑 *STOP:* `{s['stop']}`
📊 *R/R:* `1:{s['rr_ratio']}`
⭐ *CONFIANÇA:* `{s['confianca']}%`
━━━━━━━━━━━━━━
💡 *MOTIVO:* {s['motivo']}
    """
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except: pass

# =========================
# DASHBOARD ELITE (FAT PIG STYLE)
# =========================

DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>Fat Pig Signals - Elite Dashboard</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --gold: #f5a623; --bg: #050505; --card: #111111; --text: #ffffff; --muted: #888888; --green: #00ff88; --red: #ff3355; }
        body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); margin: 0; }
        .navbar { background: #000; padding: 20px 5%; border-bottom: 1px solid #222; display: flex; justify-content: space-between; align-items: center; }
        .logo { font-weight: 900; font-size: 24px; letter-spacing: 2px; color: var(--gold); }
        .container { max-width: 1400px; margin: 40px auto; padding: 0 20px; }
        .hero-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-bottom: 40px; }
        .stat-card { background: var(--card); padding: 30px; border-radius: 15px; border: 1px solid #222; text-align: center; position: relative; overflow: hidden; }
        .stat-card::after { content: ''; position: absolute; top: 0; left: 0; width: 100%; height: 3px; background: var(--gold); }
        .stat-val { font-size: 36px; font-weight: 800; color: var(--gold); margin-bottom: 5px; }
        .stat-label { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; }
        .main-grid { display: grid; grid-template-columns: 1.5fr 1fr; gap: 30px; }
        .elite-table { background: var(--card); border-radius: 20px; border: 1px solid #222; overflow: hidden; }
        .table-header { padding: 20px; background: #000; border-bottom: 1px solid #222; font-weight: bold; display: flex; justify-content: space-between; }
        table { width: 100%; border-collapse: collapse; }
        th { padding: 20px; text-align: left; color: var(--muted); font-size: 11px; text-transform: uppercase; }
        td { padding: 20px; border-bottom: 1px solid #1a1a1a; font-size: 14px; }
        .badge-buy { color: var(--green); background: rgba(0,255,136,0.1); padding: 5px 10px; border-radius: 5px; font-weight: bold; }
        .badge-sell { color: var(--red); background: rgba(255,51,85,0.1); padding: 5px 10px; border-radius: 5px; font-weight: bold; }
        .chart-box { background: var(--card); border-radius: 20px; border: 1px solid #222; padding: 20px; height: 500px; }
    </style>
</head>
<body>
    <div class="navbar">
        <div class="logo">FAT PIG <span style="color:#fff">ELITE</span></div>
        <div style="font-size: 12px; color: var(--green)"><i class="fas fa-shield-halved"></i> SECURE API CONNECTION</div>
    </div>
    <div class="container">
        <div class="hero-stats">
            <div class="stat-card"><div class="stat-val">{{ stats.winrate }}%</div><div class="stat-label">Winrate Global</div></div>
            <div class="stat-card"><div class="stat-val">{{ stats.total }}</div><div class="stat-label">Sinais Gerados</div></div>
            <div class="stat-card"><div class="stat-val" style="color:var(--green)">+{{ stats.profit }}%</div><div class="stat-label">Profit Acumulado</div></div>
            <div class="stat-card"><div class="stat-val">{{ stats.abertos }}</div><div class="stat-label">Sinais Ativos</div></div>
        </div>
        <div class="main-grid">
            <div class="elite-table">
                <div class="table-header"><span><i class="fas fa-bolt" style="color:var(--gold)"></i> ÚLTIMOS SINAIS ELITE</span></div>
                <table>
                    <thead><tr><th>Par</th><th>Direção</th><th>Entrada</th><th>Confiança</th><th>R/R</th><th>Status</th></tr></thead>
                    <tbody>
                        {% for s in sinais %}
                        <tr>
                            <td><b>{{ s.simbolo }}</b></td>
                            <td><span class="{{ 'badge-buy' if s.direcao == 'COMPRA' else 'badge-sell' }}">{{ s.direcao }}</span></td>
                            <td>${{ s.entrada }}</td>
                            <td><div style="width:100%; background:#222; height:5px; border-radius:5px; margin-top:5px;"><div style="width:{{ s.confianca }}%; background:var(--gold); height:100%; border-radius:5px;"></div></div><span style="font-size:10px; color:var(--gold)">{{ s.confianca }}%</span></td>
                            <td>1:{{ s.rr_ratio }}</td>
                            <td style="color:var(--muted)">{{ s.status }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            <div class="chart-box">
                <div style="margin-bottom:15px; font-weight:bold;"><i class="fas fa-chart-line"></i> ANÁLISE EM TEMPO REAL</div>
                <div class="tradingview-widget-container" style="height: 420px;">
                    <div id="tv_chart"></div>
                    <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
                    <script type="text/javascript">
                    new TradingView.widget({
                        "autosize": true, "symbol": "BINANCE:BTCUSDT", "interval": "60", "theme": "dark", "style": "1", "locale": "br", "container_id": "tv_chart"
                    });
                    </script>
                </div>
            </div>
        </div>
    </div>
</body>
</html>
'''

@app.route('/')
def dashboard():
    conn = sqlite3.connect(DB_PATH)
    sinais = pd.read_sql_query("SELECT * FROM sinais ORDER BY timestamp DESC LIMIT 15", conn).to_dict('records')
    stats_raw = conn.execute("SELECT COUNT(*), SUM(CASE WHEN resultado='WIN' THEN 1 ELSE 0 END), SUM(profit) FROM sinais WHERE status='FECHADO'").fetchone()
    abertos = conn.execute("SELECT COUNT(*) FROM sinais WHERE status='ABERTO'").fetchone()[0]
    conn.close()
    total = stats_raw[0] or 0
    wins = stats_raw[1] or 0
    profit = stats_raw[2] or 0.0
    stats = {"total": total, "winrate": round((wins/total*100),1) if total > 0 else 0, "profit": round(profit,2), "abertos": abertos}
    return render_template_string(DASHBOARD_TEMPLATE, stats=stats, sinais=sinais)

def worker():
    simbolos = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"]
    while True:
        for s in simbolos:
            gerar_sinal_elite(s)
            time.sleep(5)
        time.sleep(BOT_INTERVAL)

if __name__ == '__main__':
    threading.Thread(target=worker, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT)
