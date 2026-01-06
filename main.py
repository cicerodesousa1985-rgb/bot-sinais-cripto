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
BOT_INTERVAL = int(os.getenv("BOT_INTERVAL", "300"))
PORT = int(os.getenv("PORT", "10000"))

# Inicializar Exchange (Bybit)
exchange = ccxt.bybit({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})

# =========================
# BANCO DE DADOS (PERSISTÊNCIA)
# =========================
DB_PATH = "bot_signals.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sinais (
            id TEXT PRIMARY KEY,
            simbolo TEXT,
            direcao TEXT,
            entrada REAL,
            tp1 REAL,
            stop REAL,
            motivo TEXT,
            resultado TEXT,
            profit REAL,
            status TEXT,
            timestamp DATETIME,
            timestamp_fechamento DATETIME
        )
    ''')
    conn.commit()
    conn.close()

def salvar_sinal_db(s):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO sinais (id, simbolo, direcao, entrada, tp1, stop, motivo, resultado, profit, status, timestamp, timestamp_fechamento)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (s['id'], s['simbolo'], s['direcao'], s['entrada'], s['alvos'][0], s['stop_loss'], s['motivo'], s.get('resultado'), s.get('profit', 0.0), s['status'], s['timestamp'], s.get('timestamp_fechamento')))
    conn.commit()
    conn.close()

def carregar_estatisticas_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*), SUM(CASE WHEN resultado='WIN' THEN 1 ELSE 0 END), SUM(profit) FROM sinais WHERE status='FECHADO'")
    total, wins, profit = cursor.fetchone()
    conn.close()
    return total or 0, wins or 0, profit or 0.0

init_db()

# =========================
# INDICADORES TÉCNICOS PRO
# =========================

def calcular_indicadores(df):
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss)))
    
    # EMA 200 (Tendência de Longo Prazo)
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # Bandas de Bollinger
    df['sma20'] = df['close'].rolling(window=20).mean()
    df['std20'] = df['close'].rolling(window=20).std()
    df['upper_band'] = df['sma20'] + (df['std20'] * 2)
    df['lower_band'] = df['sma20'] - (df['std20'] * 2)
    
    # MACD
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    
    return df

def obter_fear_and_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/", timeout=5)
        data = r.json()
        return data['data'][0]['value'], data['data'][0]['value_classification']
    except:
        return "50", "Neutral"

# =========================
# SISTEMA DE WINRATE ATUALIZADO
# =========================

class SistemaWinrate:
    def __init__(self):
        self.lock = threading.Lock()
        self.atualizar_cache()

    def atualizar_cache(self):
        total, wins, profit = carregar_estatisticas_db()
        self.estatisticas = {
            "total_fechados": total,
            "sinais_vencedores": wins,
            "profit_total": profit,
            "winrate": (wins / total * 100) if total > 0 else 0.0,
            "ultima_atualizacao": datetime.now().strftime("%H:%M:%S")
        }

    def adicionar_sinal(self, sinal):
        sinal_completo = {**sinal, "resultado": None, "timestamp_fechamento": None, "profit": 0.0, "status": "ABERTO"}
        salvar_sinal_db(sinal_completo)
        return sinal_completo

    def atualizar_resultado(self, sinal_id, resultado, profit):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE sinais SET resultado=?, profit=?, status='FECHADO', timestamp_fechamento=? WHERE id=?
        ''', (resultado, profit, datetime.now().isoformat(), sinal_id))
        conn.commit()
        conn.close()
        self.atualizar_cache()
        
        # Notificar fechamento no Telegram
        self.notificar_fechamento_telegram(sinal_id, resultado, profit)

    def notificar_fechamento_telegram(self, sinal_id, resultado, profit):
        if not TELEGRAM_TOKEN or not CHAT_ID: return
        emoji = "✅ PROFIT" if resultado == "WIN" else "❌ STOP"
        msg = f"{emoji} *Operação Encerrada*\nID: `{sinal_id}`\nResultado: *{resultado}*\nLucro/Perda: `{profit:.2f}%`"
        try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
        except: pass

    def get_estatisticas(self):
        self.atualizar_cache()
        fng_val, fng_class = obter_fear_and_greed()
        return {
            **self.estatisticas,
            "winrate_formatado": f"{self.estatisticas['winrate']:.1f}%",
            "profit_total_formatado": f"{self.estatisticas['profit_total']:+.2f}%",
            "fng_value": fng_val,
            "fng_class": fng_class
        }

    def get_historico(self, limite=15):
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query(f"SELECT * FROM sinais ORDER BY timestamp DESC LIMIT {limite}", conn)
        conn.close()
        return df.to_dict('records')

sistema_winrate = SistemaWinrate()

# =========================
# LÓGICA DE SINAIS AVANÇADA
# =========================

def gerar_sinal_real(symbol):
    ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=200)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df = calcular_indicadores(df)
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    preco = last['close']
    
    direcao = None
    motivo = ""
    
    # ESTRATÉGIA PRO: Tendência (EMA200) + Reversão (Bollinger/RSI)
    if preco > last['ema200']: # Tendência de Alta
        if last['rsi'] < 35 and last['close'] <= last['lower_band']:
            direcao = "COMPRA"
            motivo = "Reversão na Banda Inferior (Tendência Alta)"
        elif last['macd'] > last['macd_signal'] and prev['macd'] <= prev['macd_signal']:
            direcao = "COMPRA"
            motivo = "Cruzamento MACD (Tendência Alta)"
    else: # Tendência de Baixa
        if last['rsi'] > 65 and last['close'] >= last['upper_band']:
            direcao = "VENDA"
            motivo = "Reversão na Banda Superior (Tendência Baixa)"
        elif last['macd'] < last['macd_signal'] and prev['macd'] >= prev['macd_signal']:
            direcao = "VENDA"
            motivo = "Cruzamento MACD (Tendência Baixa)"

    if not direcao: return None

    vol = df['close'].pct_change().std()
    tp = preco * (1 + vol * 2) if direcao == "COMPRA" else preco * (1 - vol * 2)
    sl = preco * (1 - vol * 2) if direcao == "COMPRA" else preco * (1 + vol * 2)

    sinal = {
        "id": f"{symbol.replace('/', '')}_{int(time.time())}",
        "simbolo": symbol, "direcao": direcao, "entrada": round(preco, 4),
        "alvos": [round(tp, 4)], "stop_loss": round(sl, 4), "motivo": motivo,
        "timestamp": datetime.now().isoformat(), "status": "ABERTO"
    }
    
    sinal_completo = sistema_winrate.adicionar_sinal(sinal)
    threading.Thread(target=monitorar_sinal, args=(sinal_completo,), daemon=True).start()
    
    # Notificar Telegram
    if TELEGRAM_TOKEN and CHAT_ID:
        emoji = "🟢" if direcao == "COMPRA" else "🔴"
        msg = f"{emoji} *NOVO SINAL PRO*\nPar: `{symbol}`\nDireção: *{direcao}*\nEntrada: `{preco}`\nAlvo: `{tp:.4f}`\nStop: `{sl:.4f}`\n💡 {motivo}"
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    
    return sinal_completo

def monitorar_sinal(sinal):
    symbol, id_sinal, tp, sl, direcao = sinal["simbolo"], sinal["id"], sinal["alvos"][0], sinal["stop_loss"], sinal["direcao"]
    for _ in range(480): # 4 horas (check a cada 30s)
        try:
            p = exchange.fetch_ticker(symbol)['last']
            if (direcao == "COMPRA" and p >= tp) or (direcao == "VENDA" and p <= tp):
                sistema_winrate.atualizar_resultado(id_sinal, "WIN", abs((tp/sinal['entrada']-1)*100))
                return
            if (direcao == "COMPRA" and p <= sl) or (direcao == "VENDA" and p >= sl):
                sistema_winrate.atualizar_resultado(id_sinal, "LOSS", -abs((sl/sinal['entrada']-1)*100))
                return
            time.sleep(30)
        except: time.sleep(60)
    # Fechamento por tempo
    p = exchange.fetch_ticker(symbol)['last']
    profit = ((p/sinal['entrada']-1)*100) if direcao == "COMPRA" else (1-p/sinal['entrada'])*100
    sistema_winrate.atualizar_resultado(id_sinal, "WIN" if profit > 0 else "LOSS", profit)

# =========================
# DASHBOARD V4 (FAT PIG SIGNALS PRO)
# =========================

DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>Fat Pig Signals V4 - Pro Dashboard</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --primary: #f5a623; --bg: #0b0e11; --card: #1e2329; --text: #eaecef; --success: #0ecb81; --danger: #f6465d; }
        body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); margin: 0; }
        .header { background: #000; padding: 15px 5%; display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid var(--primary); }
        .container { max-width: 1300px; margin: 30px auto; padding: 0 20px; }
        .top-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 30px; }
        .card { background: var(--card); padding: 20px; border-radius: 10px; text-align: center; border: 1px solid #2b3139; }
        .fng-badge { padding: 5px 15px; border-radius: 20px; font-weight: bold; font-size: 12px; margin-top: 10px; display: inline-block; }
        .grid-main { display: grid; grid-template-columns: 2fr 1fr; gap: 20px; }
        .signals-table { background: var(--card); border-radius: 12px; overflow: hidden; border: 1px solid #2b3139; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 15px; text-align: left; border-bottom: 1px solid #2b3139; font-size: 13px; }
        .chart-container { background: var(--card); padding: 15px; border-radius: 12px; border: 1px solid #2b3139; height: 450px; }
        .badge { padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 11px; }
        .buy { color: var(--success); background: rgba(14,203,129,0.1); }
        .sell { color: var(--danger); background: rgba(246,70,93,0.1); }
    </style>
</head>
<body>
    <div class="header">
        <div style="font-weight: 900; color: var(--primary); font-size: 20px;">FAT PIG <span style="color:#fff">SIGNALS V4</span></div>
        <div style="font-size: 12px;"><i class="fas fa-database"></i> DATABASE: ACTIVE</div>
    </div>
    <div class="container">
        <div class="top-stats">
            <div class="card"><div style="color:var(--primary); font-size:24px; font-weight:800;">{{ stats.winrate_formatado }}</div><div style="font-size:11px; color:#848e9c;">WINRATE GLOBAL</div></div>
            <div class="card"><div style="font-size:24px; font-weight:800;">{{ stats.total_fechados }}</div><div style="font-size:11px; color:#848e9c;">SINAIS ENCERRADOS</div></div>
            <div class="card"><div style="font-size:24px; font-weight:800; color:{{ '#0ecb81' if stats.profit_total >= 0 else '#f6465d' }}">{{ stats.profit_total_formatado }}</div><div style="font-size:11px; color:#848e9c;">PROFIT TOTAL</div></div>
            <div class="card">
                <div style="font-size:20px; font-weight:800;">{{ stats.fng_value }}</div>
                <div class="fng-badge" style="background: {{ '#0ecb81' if 'Greed' in stats.fng_class else '#f6465d' if 'Fear' in stats.fng_class else '#f5a623' }}">
                    {{ stats.fng_class }}
                </div>
                <div style="font-size:10px; color:#848e9c; margin-top:5px;">FEAR & GREED INDEX</div>
            </div>
        </div>
        <div class="grid-main">
            <div class="signals-table">
                <div style="padding:15px; background:#161a1e; font-weight:bold; border-bottom:1px solid #2b3139;">
                    <i class="fas fa-list"></i> HISTÓRICO DE SINAIS (PERSISTENTE)
                </div>
                <table>
                    <thead><tr><th>Par</th><th>Direção</th><th>Entrada</th><th>Resultado</th><th>Profit</th><th>Status</th></tr></thead>
                    <tbody>
                        {% for s in sinais %}
                        <tr>
                            <td><b>{{ s.simbolo }}</b></td>
                            <td><span class="badge {{ 'buy' if s.direcao == 'COMPRA' else 'sell' }}">{{ s.direcao }}</span></td>
                            <td>${{ s.entrada }}</td>
                            <td>{{ s.resultado or '-' }}</td>
                            <td style="color:{{ '#0ecb81' if s.profit > 0 else '#f6465d' if s.profit < 0 else '#fff' }}">{{ s.profit|round(2) }}%</td>
                            <td>{{ s.status }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            <div class="chart-container">
                <div style="font-weight:bold; margin-bottom:10px;"><i class="fas fa-chart-area"></i> LIVE MARKET (BTC/USDT)</div>
                <!-- TradingView Widget BEGIN -->
                <div class="tradingview-widget-container" style="height: 400px;">
                  <div id="tradingview_chart"></div>
                  <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
                  <script type="text/javascript">
                  new TradingView.widget({
                    "autosize": true, "symbol": "BYBIT:BTCUSDT", "interval": "60", "timezone": "Etc/UTC",
                    "theme": "dark", "style": "1", "locale": "br", "toolbar_bg": "#f1f3f6",
                    "enable_publishing": false, "hide_top_toolbar": true, "save_image": false,
                    "container_id": "tradingview_chart"
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
    return render_template_string(DASHBOARD_TEMPLATE, stats=sistema_winrate.get_estatisticas(), sinais=sistema_winrate.get_historico())

def worker():
    simbolos = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT"]
    while True:
        try:
            for s in simbolos:
                gerar_sinal_real(s)
                time.sleep(5)
            time.sleep(BOT_INTERVAL)
        except Exception as e:
            logger.error(f"Worker Error: {e}")
            time.sleep(60)

if __name__ == '__main__':
    threading.Thread(target=worker, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT)
