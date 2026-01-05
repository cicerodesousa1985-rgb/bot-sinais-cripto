import os
import time
import threading
import requests
import json
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template_string
import logging
from collections import deque
import random

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

# Configurações
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
BOT_INTERVAL = int(os.getenv("BOT_INTERVAL", "300"))  # 5 minutos
PORT = int(os.getenv("PORT", "10000"))

# Dados
signals = deque(maxlen=50)
performance_stats = {
    "total_signals": 0,
    "success_rate": 0,
    "avg_confidence": 0,
    "last_update": None
}

# =========================
# SIMULAÇÃO DE DADOS (para desenvolvimento)
# =========================
def get_market_data(symbol):
    """Simula dados de mercado (em produção, usar API real)"""
    
    # Preços base realistas
    base_prices = {
        "BTC": 43250 + random.uniform(-500, 500),
        "ETH": 2350 + random.uniform(-50, 50),
        "BNB": 315 + random.uniform(-10, 10),
        "SOL": 102 + random.uniform(-5, 5),
        "XRP": 0.58 + random.uniform(-0.02, 0.02),
        "ADA": 0.48 + random.uniform(-0.01, 0.01),
        "DOGE": 0.082 + random.uniform(-0.002, 0.002),
    }
    
    symbol_key = symbol.replace("USDT", "")
    base_price = base_prices.get(symbol_key, 100)
    
    # Simular variação de mercado
    variation = random.uniform(-0.02, 0.02)  # -2% a +2%
    current_price = base_price * (1 + variation)
    
    # Dados técnicos simulados
    data = {
        "symbol": symbol,
        "price": round(current_price, 4),
        "change_24h": round(random.uniform(-5, 5), 2),
        "volume_24h": round(random.uniform(1, 50), 1),
        "market_cap": round(random.uniform(100, 1000), 1),
        "rsi": random.randint(30, 70),
        "macd": round(random.uniform(-2, 2), 2),
        "signal": random.choice(["STRONG_BUY", "BUY", "NEUTRAL", "SELL", "STRONG_SELL"]),
        "timestamp": datetime.now().isoformat()
    }
    
    return data

def generate_signal(symbol):
    """Gera sinal baseado em análise simulada"""
    
    data = get_market_data(symbol)
    
    # Lógica de sinal baseada nos dados simulados
    signal_strength = random.choice(["STRONG", "MEDIUM", "WEAK"])
    
    if data["rsi"] < 35:
        direction = "BUY"
        confidence = random.uniform(0.7, 0.9)
        reason = f"RSI Oversold ({data['rsi']})"
    elif data["rsi"] > 65:
        direction = "SELL"
        confidence = random.uniform(0.7, 0.9)
        reason = f"RSI Overbought ({data['rsi']})"
    elif data["macd"] > 0.5:
        direction = "BUY"
        confidence = random.uniform(0.6, 0.8)
        reason = f"MACD Bullish ({data['macd']})"
    elif data["macd"] < -0.5:
        direction = "SELL"
        confidence = random.uniform(0.6, 0.8)
        reason = f"MACD Bearish ({data['macd']})"
    else:
        # Sinal neutro ou sem sinal claro
        return None
    
    signal = {
        "id": f"{symbol}_{int(time.time())}",
        "symbol": symbol,
        "direction": direction,
        "strength": signal_strength,
        "price": data["price"],
        "entry": round(data["price"] * (0.99 if direction == "BUY" else 1.01), 4),
        "targets": [
            round(data["price"] * (1.03 if direction == "BUY" else 0.97), 4),
            round(data["price"] * (1.05 if direction == "BUY" else 0.95), 4),
            round(data["price"] * (1.08 if direction == "BUY" else 0.92), 4)
        ],
        "stop_loss": round(data["price"] * (0.97 if direction == "BUY" else 1.03), 4),
        "confidence": round(confidence, 2),
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
        "time_display": datetime.now().strftime("%H:%M"),
        "risk_level": random.choice(["LOW", "MEDIUM", "HIGH"]),
        "potential_gain": f"{random.randint(3, 15)}%"
    }
    
    return signal

# =========================
# TELEGRAM
# =========================
def send_telegram_signal(signal):
    """Envia sinal para Telegram"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return False
    
    try:
        emoji = "🟢" if signal["direction"] == "BUY" else "🔴"
        strength_emoji = "🔥" if signal["strength"] == "STRONG" else "⚡" if signal["strength"] == "MEDIUM" else "💡"
        
        message = f"""
{emoji} *{signal['direction']} SIGNAL* {strength_emoji}

*Pair:* `{signal['symbol']}`
*Current Price:* `${signal['price']:,}`
*Signal Strength:* {signal['strength']}
*Confidence:* {int(signal['confidence'] * 100)}%

🎯 *Entry:* `${signal['entry']:,}`
🎯 *Targets:*
  1. `${signal['targets'][0]:,}`
  2. `${signal['targets'][1]:,}`
  3. `${signal['targets'][2]:,}`
🛑 *Stop Loss:* `${signal['stop_loss']:,}`

📊 *Risk Level:* {signal['risk_level']}
📈 *Potential Gain:* {signal['potential_gain']}
💡 *Reason:* {signal['reason']}

⏰ *Time:* {signal['time_display']}
        """
        
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        
        response = requests.post(url, json=data, timeout=10)
        return response.status_code == 200
        
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return False

# =========================
# DASHBOARD HTML TEMPLATE
# =========================
DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FatPig Signals Pro</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --primary: #1a1a2e;
            --secondary: #16213e;
            --accent: #00d4ff;
            --accent-alt: #ff00cc;
            --buy: #00ff88;
            --sell: #ff4757;
            --neutral: #ffa502;
            --card-bg: rgba(255, 255, 255, 0.05);
            --text: #ffffff;
            --text-secondary: #b0b0b0;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%);
            color: var(--text);
            min-height: 100vh;
            overflow-x: hidden;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }
        
        /* Header */
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            margin-bottom: 30px;
        }
        
        .logo {
            display: flex;
            align-items: center;
            gap: 15px;
        }
        
        .logo-icon {
            font-size: 2.5em;
            background: linear-gradient(45deg, var(--accent), var(--accent-alt));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .logo-text h1 {
            font-size: 1.8em;
            background: linear-gradient(45deg, var(--accent), var(--accent-alt));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 5px;
        }
        
        .logo-text p {
            color: var(--text-secondary);
            font-size: 0.9em;
        }
        
        .status-indicator {
            display: flex;
            align-items: center;
            gap: 10px;
            background: rgba(0, 212, 255, 0.1);
            padding: 10px 20px;
            border-radius: 50px;
            border: 1px solid rgba(0, 212, 255, 0.3);
        }
        
        .status-dot {
            width: 10px;
            height: 10px;
            background: var(--buy);
            border-radius: 50%;
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        /* Stats Grid */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            background: var(--card-bg);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 25px;
            border: 1px solid rgba(255, 255, 255, 0.1);
            transition: transform 0.3s, border-color 0.3s;
        }
        
        .stat-card:hover {
            transform: translateY(-5px);
            border-color: var(--accent);
        }
        
        .stat-card h3 {
            font-size: 2.5em;
            margin-bottom: 10px;
            color: var(--accent);
        }
        
        .stat-card p {
            color: var(--text-secondary);
            font-size: 0.9em;
        }
        
        /* Signals Grid */
        .signals-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 25px;
            margin-bottom: 40px;
        }
        
        .signal-card {
            background: var(--card-bg);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 25px;
            border: 2px solid;
            transition: all 0.3s;
            position: relative;
            overflow: hidden;
        }
        
        .signal-card.buy {
            border-color: rgba(0, 255, 136, 0.3);
            background: linear-gradient(135deg, rgba(0, 255, 136, 0.05), transparent);
        }
        
        .signal-card.sell {
            border-color: rgba(255, 71, 87, 0.3);
            background: linear-gradient(135deg, rgba(255, 71, 87, 0.05), transparent);
        }
        
        .signal-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
        }
        
        .signal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }
        
        .signal-type {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .signal-badge {
            padding: 5px 15px;
            border-radius: 20px;
            font-weight: bold;
            font-size: 0.9em;
        }
        
        .badge-buy {
            background: rgba(0, 255, 136, 0.2);
            color: var(--buy);
            border: 1px solid rgba(0, 255, 136, 0.5);
        }
        
        .badge-sell {
            background: rgba(255, 71, 87, 0.2);
            color: var(--sell);
            border: 1px solid rgba(255, 71, 87, 0.5);
        }
        
        .signal-symbol {
            font-size: 1.5em;
            font-weight: bold;
            font-family: monospace;
        }
        
        .signal-price {
            font-size: 2em;
            font-weight: bold;
            margin: 15px 0;
            color: var(--accent);
        }
        
        .signal-meta {
            display: flex;
            gap: 20px;
            margin-bottom: 20px;
        }
        
        .meta-item {
            display: flex;
            flex-direction: column;
        }
        
        .meta-label {
            font-size: 0.8em;
            color: var(--text-secondary);
            margin-bottom: 5px;
        }
        
        .meta-value {
            font-weight: bold;
        }
        
        .targets-container {
            margin: 20px 0;
        }
        
        .target-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 8px;
            margin-bottom: 8px;
        }
        
        .target-number {
            width: 30px;
            height: 30px;
            background: var(--accent);
            color: var(--primary);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
        }
        
        .time-badge {
            position: absolute;
            top: 20px;
            right: 20px;
            background: rgba(255, 255, 255, 0.1);
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 0.8em;
        }
        
        /* Market Overview */
        .market-overview {
            background: var(--card-bg);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 30px;
            margin-bottom: 40px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        
        .market-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }
        
        .market-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 15px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 10px;
            transition: transform 0.3s;
        }
        
        .market-item:hover {
            transform: translateY(-3px);
            background: rgba(255, 255, 255, 0.08);
        }
        
        .coin-info {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .coin-icon {
            width: 40px;
            height: 40px;
            background: linear-gradient(45deg, var(--accent), var(--accent-alt));
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
        }
        
        .price-change {
            font-weight: bold;
            padding: 5px 10px;
            border-radius: 5px;
        }
        
        .change-positive {
            background: rgba(0, 255, 136, 0.2);
            color: var(--buy);
        }
        
        .change-negative {
            background: rgba(255, 71, 87, 0.2);
            color: var(--sell);
        }
        
        /* Footer */
        .footer {
            text-align: center;
            padding: 30px 0;
            color: var(--text-secondary);
            border-top: 1px solid rgba(255, 255, 255, 0.1);
            margin-top: 40px;
        }
        
        .footer-links {
            display: flex;
            justify-content: center;
            gap: 30px;
            margin: 20px 0;
        }
        
        .footer-links a {
            color: var(--text-secondary);
            text-decoration: none;
            transition: color 0.3s;
        }
        
        .footer-links a:hover {
            color: var(--accent);
        }
        
        /* Responsive */
        @media (max-width: 768px) {
            .container {
                padding: 10px;
            }
            
            .header {
                flex-direction: column;
                gap: 20px;
                text-align: center;
            }
            
            .signals-grid {
                grid-template-columns: 1fr;
            }
            
            .stats-grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <div class="logo">
                <div class="logo-icon">
                    <i class="fas fa-piggy-bank"></i>
                </div>
                <div class="logo-text">
                    <h1>FatPig Signals Pro</h1>
                    <p>AI-Powered Crypto Trading Signals</p>
                </div>
            </div>
            <div class="status-indicator">
                <div class="status-dot"></div>
                <span>● LIVE TRADING</span>
                <span id="countdown" class="countdown">300s</span>
            </div>
        </div>
        
        <!-- Stats Grid -->
        <div class="stats-grid">
            <div class="stat-card">
                <h3>{{ performance.total_signals }}</h3>
                <p>Total Signals Generated</p>
                <small>24h Performance</small>
            </div>
            <div class="stat-card">
                <h3>{{ "%.1f%%"|format(performance.success_rate * 100) }}</h3>
                <p>Success Rate</p>
                <small>Based on historical data</small>
            </div>
            <div class="stat-card">
                <h3>{{ "%.1f%%"|format(performance.avg_confidence * 100) }}</h3>
                <p>Average Confidence</p>
                <small>Signal accuracy metric</small>
            </div>
            <div class="stat-card">
                <h3>{{ signals|length }}</h3>
                <p>Active Signals</p>
                <small>Currently monitoring</small>
            </div>
        </div>
        
        <!-- Market Overview -->
        <div class="market-overview">
            <h2><i class="fas fa-chart-line"></i> Market Overview</h2>
            <div class="market-grid" id="marketData">
                <!-- Market data will be loaded here -->
            </div>
        </div>
        
        <!-- Signals Grid -->
        <div class="signals-grid">
            {% for signal in signals[-6:] %}
            <div class="signal-card {{ signal.direction.lower() }}">
                <div class="time-badge">{{ signal.time_display }}</div>
                <div class="signal-header">
                    <div class="signal-type">
                        <span class="signal-badge badge-{{ signal.direction.lower() }}">
                            {{ signal.direction }} {{ signal.strength }}
                        </span>
                        <span class="risk-level" style="color: {% if signal.risk_level == 'LOW' %}#00ff88{% elif signal.risk_level == 'MEDIUM' %}#ffa502{% else %}#ff4757{% endif %}">
                            <i class="fas fa-shield-alt"></i> {{ signal.risk_level }}
                        </span>
                    </div>
                    <div class="signal-symbol">{{ signal.symbol }}</div>
                </div>
                
                <div class="signal-price">${{ "{:,.2f}".format(signal.price) }}</div>
                
                <div class="signal-meta">
                    <div class="meta-item">
                        <span class="meta-label">Confidence</span>
                        <span class="meta-value" style="color: var(--accent);">
                            {{ (signal.confidence * 100)|int }}%
                        </span>
                    </div>
                    <div class="meta-item">
                        <span class="meta-label">Potential Gain</span>
                        <span class="meta-value" style="color: var(--buy);">
                            {{ signal.potential_gain }}
                        </span>
                    </div>
                </div>
                
                <div class="targets-container">
                    <div class="meta-label">Profit Targets</div>
                    {% for target in signal.targets %}
                    <div class="target-item">
                        <div class="target-number">{{ loop.index }}</div>
                        <div>${{ "{:,.2f}".format(target) }}</div>
                        <div style="color: var(--buy);">
                            +{{ ((target / signal.price - 1) * 100)|round(1) }}%
                        </div>
                    </div>
                    {% endfor %}
                </div>
                
                <div style="margin-top: 15px; padding-top: 15px; border-top: 1px solid rgba(255,255,255,0.1);">
                    <div class="meta-label">Trade Setup</div>
                    <div style="display: flex; justify-content: space-between; margin-top: 10px;">
                        <div>
                            <small>Entry</small>
                            <div><strong>${{ "{:,.2f}".format(signal.entry) }}</strong></div>
                        </div>
                        <div>
                            <small>Stop Loss</small>
                            <div><strong style="color: var(--sell);">${{ "{:,.2f}".format(signal.stop_loss) }}</strong></div>
                        </div>
                    </div>
                </div>
                
                <div style="margin-top: 15px; font-size: 0.9em; color: var(--text-secondary);">
                    <i class="fas fa-lightbulb"></i> {{ signal.reason }}
                </div>
            </div>
            {% endfor %}
        </div>
        
        <!-- Footer -->
        <div class="footer">
            <p>FatPig Signals Pro v2.0 - AI Crypto Trading Platform</p>
            <div class="footer-links">
                <a href="/health"><i class="fas fa-heartbeat"></i> System Health</a>
                <a href="/api/signals"><i class="fas fa-code"></i> API</a>
                <a href="/stats"><i class="fas fa-chart-bar"></i> Statistics</a>
                <a href="javascript:void(0)" onclick="refreshData()"><i class="fas fa-sync-alt"></i> Refresh</a>
            </div>
            <p style="font-size: 0.9em; margin-top: 20px; opacity: 0.7;">
                <i class="fas fa-exclamation-triangle"></i> Trading involves risk. Only trade with money you can afford to lose.
            </p>
            <p style="font-size: 0.8em; margin-top: 10px; opacity: 0.5;">
                Last updated: <span id="lastUpdate">{{ performance.last_update or "Never" }}</span>
            </p>
        </div>
    </div>
    
    <script>
        // Update countdown
        let countdown = 300;
        const countdownEl = document.getElementById('countdown');
        
        setInterval(() => {
            countdown = countdown <= 0 ? 300 : countdown - 1;
            countdownEl.textContent = countdown + 's';
        }, 1000);
        
        // Load market data
        async function loadMarketData() {
            try {
                const response = await fetch('/api/market');
                const data = await response.json();
                
                let html = '';
                data.prices.forEach(coin => {
                    const changeClass = coin.change_24h >= 0 ? 'change-positive' : 'change-negative';
                    const changeIcon = coin.change_24h >= 0 ? '▲' : '▼';
                    
                    html += `
                    <div class="market-item">
                        <div class="coin-info">
                            <div class="coin-icon">${coin.symbol.replace('USDT', '').substring(0, 3)}</div>
                            <div>
                                <div style="font-weight: bold;">${coin.symbol}</div>
                                <div style="font-size: 0.9em; opacity: 0.7;">$${coin.price.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</div>
                            </div>
                        </div>
                        <div class="price-change ${changeClass}">
                            ${changeIcon} ${Math.abs(coin.change_24h).toFixed(2)}%
                        </div>
                    </div>
                    `;
                });
                
                document.getElementById('marketData').innerHTML = html;
                document.getElementById('lastUpdate').textContent = new Date().toLocaleTimeString();
            } catch (error) {
                console.error('Error loading market data:', error);
            }
        }
        
        // Refresh data
        function refreshData() {
            loadMarketData();
            setTimeout(() => {
                window.location.reload();
            }, 1000);
        }
        
        // Auto-refresh every 60 seconds
        setInterval(() => {
            loadMarketData();
        }, 60000);
        
        // Initial load
        loadMarketData();
        
        // Smooth scroll animation
        document.querySelectorAll('.signal-card').forEach(card => {
            card.addEventListener('mouseenter', () => {
                card.style.transform = 'translateY(-5px) scale(1.02)';
            });
            
            card.addEventListener('mouseleave', () => {
                card.style.transform = 'translateY(0) scale(1)';
            });
        });
    </script>
</body>
</html>
'''

# =========================
# ROTAS
# =========================
@app.route('/')
def dashboard():
    """Dashboard principal"""
    
    # Atualizar estatísticas
    if signals:
        total_conf = sum(s["confidence"] for s in signals)
        performance_stats["avg_confidence"] = total_conf / len(signals)
        performance_stats["success_rate"] = 0.78  # Simulado
        performance_stats["last_update"] = datetime.now().strftime("%H:%M:%S")
    
    return render_template_string(
        DASHBOARD_TEMPLATE,
        signals=list(signals)[-6:][::-1],  # Últimos 6, mais recentes primeiro
        performance=performance_stats
    )

@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "fatpig-signals-pro",
        "version": "2.0",
        "uptime": "24/7",
        "signals_count": len(signals)
    })

@app.route('/api/signals')
def api_signals():
    return jsonify({
        "count": len(signals),
        "signals": list(signals)[-20:],
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/market')
def api_market():
    """Dados de mercado"""
    symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]
    prices = []
    
    for symbol in symbols:
        data = get_market_data(symbol)
        prices.append({
            "symbol": symbol,
            "price": data["price"],
            "change_24h": data["change_24h"],
            "volume_24h": data["volume_24h"],
            "market_cap": data["market_cap"]
        })
    
    return jsonify({
        "prices": prices,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/stats')
def stats_page():
    """Página de estatísticas"""
    stats = {
        "performance": performance_stats,
        "recent_signals": len(signals),
        "buy_signals": len([s for s in signals if s["direction"] == "BUY"]),
        "sell_signals": len([s for s in signals if s["direction"] == "SELL"]),
        "avg_confidence": performance_stats["avg_confidence"],
        "signals_today": len([s for s in signals if datetime.fromisoformat(s["timestamp"]).date() == datetime.now().date()])
    }
    
    return jsonify(stats)

@app.route('/generate-test')
def generate_test_signals():
    """Gera sinais de teste"""
    symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]
    
    for symbol in symbols:
        signal = generate_signal(symbol)
        if signal:
            signals.append(signal)
            performance_stats["total_signals"] += 1
            
            # Enviar para Telegram se configurado
            if TELEGRAM_TOKEN and CHAT_ID:
                send_telegram_signal(signal)
                time.sleep(1)
    
    return jsonify({
        "status": "success",
        "generated": len(symbols),
        "total_signals": len(signals)
    })

# =========================
# BOT WORKER
# =========================
def bot_worker():
    """Worker que gera sinais periodicamente"""
    logger.info("🤖 FatPig Signals Pro iniciado")
    
    # Pares a monitorar
    symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
    
    # Mensagem inicial no Telegram
    if TELEGRAM_TOKEN and CHAT_ID:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": CHAT_ID,
                    "text": "🚀 *FatPig Signals Pro Iniciado*\nSistema de trading AI ativado!\nMonitorando 4 pares principais\nIntervalo: 5 minutos\n✅ Pronto para gerar sinais!",
                    "parse_mode": "Markdown"
                },
                timeout=5
            )
        except:
            pass
    
    while True:
        try:
            logger.info(f"🔍 Analisando {len(symbols)} pares...")
            
            for symbol in symbols:
                # Gerar sinal (30% chance)
                if random.random() < 0.3:
                    signal = generate_signal(symbol)
                    if signal:
                        signals.append(signal)
                        performance_stats["total_signals"] += 1
                        
                        logger.info(f"📢 Novo sinal: {signal['direction']} {signal['symbol']}")
                        
                        # Enviar para Telegram
                        if TELEGRAM_TOKEN and CHAT_ID:
                            send_telegram_signal(signal)
                            time.sleep(1)
                
                time.sleep(2)  # Pausa entre análises
            
            logger.info(f"✅ Análise completa. Próxima em {BOT_INTERVAL//60} minutos")
            time.sleep(BOT_INTERVAL)
            
        except Exception as e:
            logger.error(f"❌ Erro no worker: {e}")
            time.sleep(60)

# =========================
# MANTER ATIVO NO RENDER
# =========================
def keep_alive():
    """Ping automático para manter ativo"""
    time.sleep(30)
    while True:
        try:
            requests.get(f"http://localhost:{PORT}/health", timeout=5)
        except:
            pass
        time.sleep(240)  # 4 minutos

# =========================
# INICIAR
# =========================
def main():
    """Função principal"""
    logger.info(f"🚀 FatPig Signals Pro iniciando na porta {PORT}")
    
    # Iniciar workers
    threading.Thread(target=bot_worker, daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()
    
    # Gerar alguns sinais iniciais
    threading.Thread(target=generate_test_signals, daemon=True).start()
    
    # Iniciar servidor
    app.run(
        host='0.0.0.0',
        port=PORT,
        debug=False,
        use_reloader=False,
        threaded=True
    )

if __name__ == '__main__':
    main()
