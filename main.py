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

# Inicializar Exchange (Bybit - Melhor para o Render)
exchange = ccxt.bybit({
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

# =========================
# ANÁLISE TÉCNICA REAL
# =========================

def calcular_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calcular_macd(series, fast=12, slow=26, signal=9):
    exp1 = series.ewm(span=fast, adjust=False).mean()
    exp2 = series.ewm(span=slow, adjust=False).mean()
    macd = exp1 - exp2
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    return macd, signal_line

def obter_dados_mercado(symbol, timeframe='1h', limit=100):
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
    df = obter_dados_mercado(symbol)
    if df is None or len(df) < 30:
        return None

    df['rsi'] = calcular_rsi(df['close'])
    df['macd'], df['macd_signal'] = calcular_macd(df['close'])
    
    ultimo_rsi = df['rsi'].iloc[-1]
    ultimo_macd = df['macd'].iloc[-1]
    ultimo_signal = df['macd_signal'].iloc[-1]
    preco_atual = df['close'].iloc[-1]
    
    direcao = None
    motivo = ""
    
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
    threading.Thread(target=monitorar_sinal_real, args=(sinal_completo,), daemon=True).start()
    return sinal_completo

def monitorar_sinal_real(sinal):
    symbol = sinal["simbolo"]
    id_sinal = sinal["id"]
    tp1 = sinal["alvos"][0]
    stop = sinal["stop_loss"]
    direcao = sinal["direcao"]
    
    tempo_limite = datetime.now() + timedelta(hours=4)
    
    while datetime.now() < tempo_limite:
        try:
            ticker = exchange.fetch_ticker(symbol)
            preco_atual = ticker['last']
            
            if direcao == "COMPRA":
                if preco_atual >= tp1:
                    profit = ((tp1 / sinal["entrada"]) - 1) * 100
                    sistema_winrate.atualizar_resultado(id_sinal, "WIN", profit)
                    return
                elif preco_atual <= stop:
                    profit = ((stop / sinal["entrada"]) - 1) * 100
                    sistema_winrate.atualizar_resultado(id_sinal, "LOSS", profit)
                    return
            else:
                if preco_atual <= tp1:
                    profit = (1 - (tp1 / sinal["entrada"])) * 100
                    sistema_winrate.atualizar_resultado(id_sinal, "WIN", profit)
                    return
                elif preco_atual >= stop:
                    profit = (1 - (stop / sinal["entrada"])) * 100
                    sistema_winrate.atualizar_resultado(id_sinal, "LOSS", profit)
                    return
            time.sleep(30)
        except:
            time.sleep(60)
            
    try:
        ticker = exchange.fetch_ticker(symbol)
        preco_final = ticker['last']
        profit = ((preco_final / sinal["entrada"]) - 1) * 100 if direcao == "COMPRA" else (1 - (preco_final / sinal["entrada"])) * 100
        sistema_winrate.atualizar_resultado(id_sinal, "WIN" if profit > 0 else "LOSS", profit)
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
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": mensagem, "parse_mode": "Markdown"}, timeout=10)
    except:
        pass

# =========================
# DASHBOARD (ESTILO FAT PIG SIGNALS)
# =========================

DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Fat Pig Signals - Dashboard Pro</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root {
            --primary: #f5a623;
            --bg: #0b0e11;
            --card-bg: #1e2329;
            --text: #eaecef;
            --text-muted: #848e9c;
            --success: #0ecb81;
            --danger: #f6465d;
        }
        
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }
        
        .header { 
            background: #000; 
            padding: 20px 5%; 
            display: flex; 
            justify-content: space-between; 
            align-items: center;
            border-bottom: 2px solid var(--primary);
        }
        
        .logo { font-size: 24px; font-weight: 900; color: var(--primary); text-transform: uppercase; letter-spacing: 2px; }
        .logo span { color: #fff; }
        
        .container { max-width: 1200px; margin: 40px auto; padding: 0 20px; }
        
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-bottom: 40px; }
        .stat-card { background: var(--card-bg); padding: 30px; border-radius: 12px; text-align: center; border: 1px solid #2b3139; transition: transform 0.3s; }
        .stat-card:hover { transform: translateY(-5px); border-color: var(--primary); }
        .stat-value { font-size: 32px; font-weight: 800; margin-bottom: 5px; }
        .stat-label { color: var(--text-muted); font-size: 14px; text-transform: uppercase; letter-spacing: 1px; }
        
        .signals-section { background: var(--card-bg); border-radius: 16px; overflow: hidden; border: 1px solid #2b3139; }
        .section-header { padding: 20px 30px; background: #161a1e; border-bottom: 1px solid #2b3139; display: flex; justify-content: space-between; align-items: center; }
        
        table { width: 100%; border-collapse: collapse; }
        th { text-align: left; padding: 20px 30px; color: var(--text-muted); font-size: 12px; text-transform: uppercase; border-bottom: 1px solid #2b3139; }
        td { padding: 20px 30px; border-bottom: 1px solid #2b3139; font-size: 14px; }
        
        .badge { padding: 6px 12px; border-radius: 6px; font-weight: 600; font-size: 12px; }
        .badge-buy { background: rgba(14, 203, 129, 0.15); color: var(--success); }
        .badge-sell { background: rgba(246, 70, 93, 0.15); color: var(--danger); }
        .badge-win { background: var(--success); color: #000; }
        .badge-loss { background: var(--danger); color: #fff; }
        .badge-open { background: #474d57; color: #fff; }
        
        .profit-pos { color: var(--success); font-weight: bold; }
        .profit-neg { color: var(--danger); font-weight: bold; }
        
        .footer { text-align: center; padding: 40px; color: var(--text-muted); font-size: 12px; }
        
        @media (max-width: 768px) {
            .stats-grid { grid-template-columns: 1fr; }
            th:nth-child(4), td:nth-child(4), th:nth-child(5), td:nth-child(5) { display: none; }
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="logo">FAT PIG <span>SIGNALS</span></div>
        <div style="color: var(--success); font-size: 12px;"><i class="fas fa-circle"></i> SISTEMA ATIVO</div>
    </div>
    
    <div class="container">
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value" style="color: var(--primary)">{{ stats.winrate_formatado }}</div>
                <div class="stat-label">Winrate Global</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ stats.sinais_hoje }}</div>
                <div class="stat-label">Sinais Hoje</div>
            </div>
            <div class="stat-card">
                <div class="stat-value {{ 'profit-pos' if stats.profit_total >= 0 else 'profit-neg' }}">{{ stats.profit_total_formatado }}</div>
                <div class="stat-label">Profit Acumulado</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{{ stats.sinais_em_aberto }}</div>
                <div class="stat-label">Operações em Aberto</div>
            </div>
        </div>
        
        <div class="signals-section">
            <div class="section-header">
                <h2 style="font-size: 18px;"><i class="fas fa-bolt" style="color: var(--primary)"></i> ÚLTIMOS SINAIS REAIS</h2>
                <span style="font-size: 12px; color: var(--text-muted)">Atualizado em tempo real</span>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Par</th>
                        <th>Direção</th>
                        <th>Entrada</th>
                        <th>Resultado</th>
                        <th>Profit</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {% for s in sinais %}
                    <tr>
                        <td style="font-weight: bold;">{{ s.simbolo }}</td>
                        <td><span class="badge {{ 'badge-buy' if s.direcao == 'COMPRA' else 'badge-sell' }}">{{ s.direcao }}</span></td>
                        <td>${{ "{:,.2f}".format(s.entrada) }}</td>
                        <td>
                            {% if s.resultado %}
                                <span class="badge {{ 'badge-win' if s.resultado == 'WIN' else 'badge-loss' }}">{{ s.resultado }}</span>
                            {% else %}
                                <span class="badge badge-open">AGUARDANDO</span>
                            {% endif %}
                        </td>
                        <td class="{{ 'profit-pos' if s.profit > 0 else 'profit-neg' if s.profit < 0 else '' }}">
                            {{ s.profit|round(2) }}%
                        </td>
                        <td style="color: var(--text-muted); font-size: 12px;">{{ s.status }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    
    <div class="footer">
        &copy; 2026 FAT PIG SIGNALS - ALGORITMO DE ANÁLISE TÉCNICA PRO<br>
        <span style="opacity: 0.5">Este dashboard é apenas para fins educacionais e de monitoramento.</span>
    </div>
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

def worker_principal():
    logger.info("🤖 Bot V3 Iniciado - Estilo Fat Pig Signals")
    simbolos = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT", "DOGE/USDT"]
    while True:
        try:
            for symbol in simbolos:
                sinal = gerar_sinal_real(symbol)
                if sinal:
                    logger.info(f"📢 Novo sinal real: {sinal['direcao']} {symbol}")
                    enviar_telegram_sinal(sinal)
                time.sleep(2)
            time.sleep(BOT_INTERVAL)
        except Exception as e:
            logger.error(f"Erro no worker: {e}")
            time.sleep(60)

if __name__ == '__main__':
    threading.Thread(target=worker_principal, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT)
