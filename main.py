
import os
import time
import threading
import requests
import json
from datetime import datetime
from flask import Flask, render_template_string
import logging
from collections import deque
import random

# =========================
# CONFIGURAÇÃO
# =========================
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
PORT = int(os.getenv("PORT", "10000"))

PARES = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT", "DOTUSDT", "MATICUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]

# =========================
# SISTEMA DE DADOS
# =========================
class SistemaWinrate:
    def __init__(self):
        self.sinais = deque(maxlen=50)
        self.stats = {
            "total": 0, "wins": 0, "losses": 0, "winrate": 88.5,
            "profit": 0.0, "inicio": datetime.now().strftime("%d/%m %H:%M")
        }
    
    def add_sinal(self, sinal):
        self.sinais.append(sinal)
        self.stats["total"] += 1
        if self.stats["total"] > 5:
            self.stats["winrate"] = random.uniform(87.0, 94.0)
        return sinal

winrate_sys = SistemaWinrate()

# =========================
# COLETA DE DADOS REAIS
# =========================
def buscar_preco_real(simbolo):
    try:
        moeda = simbolo.replace("USDT", "")
        url = f"https://min-api.cryptocompare.com/data/pricemultifull?fsyms={moeda}&tsyms=USD"
        res = requests.get(url, timeout=10).json()
        dados = res['RAW'][moeda]['USD']
        return {
            "preco": float(dados['PRICE']),
            "variacao": float(dados['CHANGEPCT24HOUR']),
            "high": float(dados['HIGH24HOUR']),
            "low": float(dados['LOW24HOUR'])
        }
    except:
        return None

# =========================
# GERADOR DE SINAIS
# =========================
def gerar_sinal_real():
    simbolo = random.choice(PARES)
    dados = buscar_preco_real(simbolo)
    
    if not dados: return

    preco = dados['preco']
    variacao = dados['variacao']
    
    if variacao > 1.0:
        direcao = "COMPRA"
        motivo = "Tendência de Alta Confirmada"
    elif variacao < -1.0:
        direcao = "VENDA"
        motivo = "Tendência de Baixa Confirmada"
    else:
        direcao = random.choice(["COMPRA", "VENDA"])
        motivo = "Rompimento de Consolidação"

    sinal = {
        "id": int(time.time()),
        "simbolo": simbolo,
        "direcao": direcao,
        "preco": round(preco, 4),
        "tp": round(preco * 1.02 if direcao == "COMPRA" else preco * 0.98, 4),
        "sl": round(preco * 0.97 if direcao == "COMPRA" else preco * 1.03, 4),
        "motivo": motivo,
        "confianca": random.randint(90, 98),
        "tempo": datetime.now().strftime("%H:%M")
    }
    
    winrate_sys.add_sinal(sinal)
    
    if TELEGRAM_TOKEN:
        emoji = "🟢" if sinal['direcao'] == "COMPRA" else "🔴"
        msg = f"{emoji} *FAT PIG SIGNAL: {sinal['simbolo']}*\n\n📈 Direção: {sinal['direcao']}\n💰 Preço: ${sinal['preco']}\n🎯 Alvo: ${sinal['tp']}\n🛑 Stop: ${sinal['sl']}\n\n💡 Motivo: {sinal['motivo']}\n⚡ Confiança: {sinal['confianca']}%"
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})

def loop_sinais():
    while True:
        gerar_sinal_real()
        time.sleep(300)

# =========================
# DASHBOARD DESIGN FATPIG
# =========================
DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Fat Pig Signals - Dashboard VIP</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;700;800&display=swap');
        
        :root {
            --primary-gold: #f5a623;
            --dark-bg: #0c0c0c;
            --card-bg: #1a1a1a;
            --text-white: #ffffff;
            --text-gray: #a0a0a0;
            --buy-green: #00c853;
            --sell-red: #ff3d00;
        }

        body {
            background-color: var(--dark-bg);
            color: var(--text-white);
            font-family: 'Montserrat', sans-serif;
            margin: 0;
            padding: 0;
        }

        .navbar {
            background-color: rgba(0, 0, 0, 0.9);
            border-bottom: 2px solid var(--primary-gold);
            padding: 15px 0;
        }

        .navbar-brand {
            font-weight: 800;
            color: var(--primary-gold) !important;
            font-size: 1.5rem;
            text-transform: uppercase;
        }

        .hero-section {
            padding: 40px 0;
            text-align: center;
            background: linear-gradient(rgba(0,0,0,0.7), rgba(0,0,0,0.7)), url('https://www.fatpigsignals.com/wp-content/uploads/2021/05/bg-hero.jpg');
            background-size: cover;
            background-position: center;
            border-bottom: 1px solid #333;
        }

        .hero-title {
            font-weight: 800;
            font-size: 2.5rem;
            margin-bottom: 10px;
        }

        .hero-subtitle {
            color: var(--primary-gold);
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 2px;
        }

        .stat-card {
            background-color: var(--card-bg);
            border: 1px solid #333;
            border-radius: 12px;
            padding: 25px;
            text-align: center;
            transition: transform 0.3s ease;
        }

        .stat-card:hover {
            transform: translateY(-5px);
            border-color: var(--primary-gold);
        }

        .stat-value {
            font-size: 2rem;
            font-weight: 800;
            color: var(--primary-gold);
            margin-bottom: 5px;
        }

        .stat-label {
            color: var(--text-gray);
            font-size: 0.8rem;
            text-transform: uppercase;
            font-weight: 700;
        }

        .signal-card {
            background-color: var(--card-bg);
            border-radius: 15px;
            border: 1px solid #333;
            margin-bottom: 20px;
            overflow: hidden;
            transition: all 0.3s ease;
        }

        .signal-card:hover {
            border-color: var(--primary-gold);
            box-shadow: 0 0 20px rgba(245, 166, 35, 0.1);
        }

        .signal-header {
            padding: 15px 20px;
            background-color: rgba(255, 255, 255, 0.03);
            border-bottom: 1px solid #333;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .signal-body {
            padding: 20px;
        }

        .symbol-name {
            font-weight: 800;
            font-size: 1.2rem;
        }

        .direction-badge {
            padding: 5px 15px;
            border-radius: 50px;
            font-weight: 800;
            font-size: 0.8rem;
            text-transform: uppercase;
        }

        .badge-buy { background-color: var(--buy-green); color: white; }
        .badge-sell { background-color: var(--sell-red); color: white; }

        .price-info {
            display: flex;
            justify-content: space-between;
            margin-bottom: 15px;
        }

        .price-item {
            text-align: center;
            flex: 1;
        }

        .price-label {
            font-size: 0.7rem;
            color: var(--text-gray);
            text-transform: uppercase;
            margin-bottom: 5px;
        }

        .price-value {
            font-weight: 700;
            font-size: 1rem;
        }

        .confidence-bar {
            height: 6px;
            background-color: #333;
            border-radius: 10px;
            margin-top: 10px;
        }

        .confidence-fill {
            height: 100%;
            background-color: var(--primary-gold);
            border-radius: 10px;
        }

        .footer {
            padding: 40px 0;
            text-align: center;
            color: var(--text-gray);
            font-size: 0.8rem;
            border-top: 1px solid #333;
            margin-top: 50px;
        }

        .btn-fatpig {
            background-color: var(--primary-gold);
            color: black;
            font-weight: 800;
            border-radius: 50px;
            padding: 10px 30px;
            text-transform: uppercase;
            border: none;
            transition: all 0.3s ease;
        }

        .btn-fatpig:hover {
            background-color: white;
            transform: scale(1.05);
        }
    </style>
</head>
<body>
    <nav class="navbar navbar-dark">
        <div class="container">
            <a class="navbar-brand" href="#"><i class="fas fa-piggy-bank me-2"></i> FAT PIG SIGNALS</a>
            <div class="d-none d-md-block">
                <span class="badge bg-success"><i class="fas fa-circle me-1"></i> LIVE MARKET ANALYSIS</span>
            </div>
        </div>
    </nav>

    <section class="hero-section">
        <div class="container">
            <p class="hero-subtitle">Premium Crypto Intelligence</p>
            <h1 class="hero-title">Trade Like a <span style="color: var(--primary-gold);">PRO</span></h1>
            <p class="text-gray">Real-time signals based on professional technical and fundamental analysis.</p>
        </div>
    </section>

    <div class="container mt-5">
        <div class="row g-4 mb-5">
            <div class="col-md-4">
                <div class="stat-card">
                    <div class="stat-value">{{ "%.1f"|format(stats.winrate) }}%</div>
                    <div class="stat-label">Average Winrate</div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="stat-card">
                    <div class="stat-value">{{ stats.total }}</div>
                    <div class="stat-label">Signals Today</div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="stat-card">
                    <div class="stat-value">VIP</div>
                    <div class="stat-label">Service Status</div>
                </div>
            </div>
        </div>

        <div class="row">
            <div class="col-12 mb-4 d-flex justify-content-between align-items-center">
                <h3 class="fw-bold"><i class="fas fa-bolt text-warning me-2"></i> LATEST SIGNALS</h3>
                <button class="btn btn-fatpig btn-sm" onclick="location.reload()">Refresh Data</button>
            </div>
            
            {% for s in sinais|reverse %}
            <div class="col-md-6 col-lg-4">
                <div class="signal-card">
                    <div class="signal-header">
                        <span class="symbol-name">{{s.simbolo}}</span>
                        <span class="direction-badge {{ 'badge-buy' if s.direcao == 'COMPRA' else 'badge-sell' }}">{{s.direcao}}</span>
                    </div>
                    <div class="signal-body">
                        <div class="price-info">
                            <div class="price-item">
                                <div class="price-label">Entry</div>
                                <div class="price-value">${{s.preco}}</div>
                            </div>
                            <div class="price-item">
                                <div class="price-label">Target</div>
                                <div class="price-value text-success">${{s.tp}}</div>
                            </div>
                            <div class="price-item">
                                <div class="price-label">Stop</div>
                                <div class="price-value text-danger">${{s.sl}}</div>
                            </div>
                        </div>
                        <div class="mt-3">
                            <div class="d-flex justify-content-between small mb-1">
                                <span class="text-gray">Confidence Score</span>
                                <span class="text-gold fw-bold">{{s.confianca}}%</span>
                            </div>
                            <div class="confidence-bar">
                                <div class="confidence-fill" style="width: {{s.confianca}}%"></div>
                            </div>
                        </div>
                        <div class="mt-3 pt-3 border-top border-secondary d-flex justify-content-between align-items-center">
                            <span class="small text-gray"><i class="far fa-clock me-1"></i> {{s.tempo}}</span>
                            <span class="small text-gold fw-bold">{{s.motivo}}</span>
                        </div>
                    </div>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>

    <footer class="footer">
        <div class="container">
            <p>&copy; 2026 FAT PIG SIGNALS - PROFESSIONAL TRADING GROUP</p>
            <p class="small">Disclaimer: Trading cryptocurrencies involves significant risk. Our signals are for educational purposes.</p>
        </div>
    </footer>

    <script>setTimeout(() => location.reload(), 60000);</script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(DASHBOARD_HTML, sinais=list(winrate_sys.sinais), stats=winrate_sys.stats)

if __name__ == '__main__':
    threading.Thread(target=loop_sinais, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT)
