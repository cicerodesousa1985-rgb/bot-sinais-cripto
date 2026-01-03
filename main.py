import os
import time
import threading
import requests
import json
from datetime import datetime, timedelta
from flask import Flask, render_template_string
import logging

# =========================
# CONFIGURAÇÃO BÁSICA
# =========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configurações
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

# Estado do bot
signals_paused = False
last_signals = []
bot_start_time = datetime.now()

# =========================
# LISTA DE PARES SIMPLES
# =========================
PAIRS = [
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 
    'XRPUSDT', 'ADAUSDT', 'DOGEUSDT', 'MATICUSDT'
]

# =========================
# FUNÇÕES BÁSICAS
# =========================
def get_binance_price(symbol):
    """Obtém preço atual da Binance"""
    try:
        url = f'https://api.binance.com/api/v3/ticker/price?symbol={symbol}'
        response = requests.get(url, timeout=5)
        data = response.json()
        return float(data['price'])
    except:
        return None

def get_binance_klines(symbol, interval='1m', limit=20):
    """Obtém dados de candles"""
    try:
        url = f'https://api.binance.com/api/v3/klines'
        params = {'symbol': symbol, 'interval': interval, 'limit': limit}
        response = requests.get(url, params=params, timeout=10)
        return response.json()
    except:
        return None

def calculate_rsi(prices, period=14):
    """Calcula RSI manualmente"""
    if len(prices) < period + 1:
        return 50
    
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_ema(prices, period):
    """Calcula EMA manualmente"""
    if len(prices) < period:
        return prices[-1] if prices else 0
    
    multiplier = 2 / (period + 1)
    ema = prices[0]
    
    for price in prices[1:]:
        ema = (price - ema) * multiplier + ema
    
    return ema

def analyze_pair(symbol):
    """Analisa um par usando estratégias simples"""
    try:
        # Obtém dados
        klines = get_binance_klines(symbol)
        if not klines:
            return None
        
        # Extrai preços de fechamento
        closes = [float(k[4]) for k in klines]  # índice 4 é close
        
        if len(closes) < 15:
            return None
        
        # Calcula indicadores
        current_price = closes[-1]
        prev_price = closes[-2]
        
        # RSI
        rsi_value = calculate_rsi(closes[-15:])
        
        # EMAs
        ema9 = calculate_ema(closes[-9:], 9)
        ema21 = calculate_ema(closes[-21:], 21)
        
        # Volume (simplificado)
        volumes = [float(k[5]) for k in klines]  # índice 5 é volume
        current_volume = volumes[-1]
        avg_volume = sum(volumes[-20:]) / len(volumes[-20:])
        
        # Análise de estratégias
        signals = []
        
        # Estratégia 1: RSI oversold/overbought
        if rsi_value < 35:
            signals.append(('RSI_OVERSOLD', 1.0))
        elif rsi_value > 65:
            signals.append(('RSI_OVERBOUGHT', -1.0))
        
        # Estratégia 2: EMA crossover
        if ema9 > ema21 and prev_price <= ema21:
            signals.append(('EMA_CROSSOVER', 1.0))
        elif ema9 < ema21 and prev_price >= ema21:
            signals.append(('EMA_CROSSUNDER', -1.0))
        
        # Estratégia 3: Volume spike
        if current_volume > avg_volume * 1.5:
            if current_price > prev_price:
                signals.append(('VOLUME_SPIKE_BUY', 0.8))
            else:
                signals.append(('VOLUME_SPIKE_SELL', -0.8))
        
        # Calcula score final
        if not signals:
            return None
        
        buy_score = sum(score for _, score in signals if score > 0)
        sell_score = abs(sum(score for _, score in signals if score < 0))
        
        # Determina sinal
        if buy_score >= 1.5:
            return {
                'symbol': symbol,
                'direction': 'BUY',
                'price': current_price,
                'score': buy_score,
                'strategies': [s[0] for s in signals if s[1] > 0]
            }
        elif sell_score >= 1.5:
            return {
                'symbol': symbol,
                'direction': 'SELL',
                'price': current_price,
                'score': sell_score,
                'strategies': [s[0] for s in signals if s[1] < 0]
            }
        
    except Exception as e:
        logger.error(f"Erro analisando {symbol}: {e}")
    
    return None

def send_telegram_message(message):
    """Envia mensagem para Telegram"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.warning("Telegram não configurado")
        return False
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        response = requests.post(url, json=data, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Erro enviando Telegram: {e}")
        return False

def check_market():
    """Verifica todos os pares"""
    global last_signals
    
    if signals_paused:
        return
    
    logger.info("🔍 Verificando mercado...")
    
    signals_found = 0
    for pair in PAIRS:
        try:
            signal = analyze_pair(pair)
            if signal:
                logger.info(f"✅ Sinal encontrado para {pair}: {signal['direction']}")
                
                # Formata mensagem
                direction_emoji = "🚀" if signal['direction'] == 'BUY' else "🔻"
                price = signal['price']
                strategies = ", ".join(signal['strategies'][:3])
                
                message = (
                    f"{direction_emoji} <b>SINAL DE {signal['direction']}</b>\n"
                    f"📊 Par: <code>{pair}</code>\n"
                    f"💰 Preço: ${price:.4f}\n"
                    f"📈 Estratégias: {strategies}\n"
                    f"🎯 Confiança: {signal['score']:.1f}/3.0\n"
                    f"🕐 Hora: {datetime.now().strftime('%H:%M:%S')}\n"
                )
                
                # Envia e armazena
                if send_telegram_message(message):
                    signal['time'] = datetime.now()
                    signal['message'] = message
                    last_signals.append(signal)
                    
                    # Mantém apenas últimos 20 sinais
                    if len(last_signals) > 20:
                        last_signals.pop(0)
                    
                    signals_found += 1
                    time.sleep(1)  # Delay entre mensagens
                
        except Exception as e:
            logger.error(f"Erro processando {pair}: {e}")
    
    if signals_found > 0:
        logger.info(f"📤 {signals_found} sinais enviados")
    else:
        logger.info("📭 Nenhum sinal encontrado")

# =========================
# DASHBOARD WEB
# =========================
@app.route('/')
def dashboard():
    """Página principal do dashboard"""
    
    # Estatísticas
    uptime = datetime.now() - bot_start_time
    hours = uptime.seconds // 3600
    minutes = (uptime.seconds % 3600) // 60
    
    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Crypto Signal Bot</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: #333;
                margin: 0;
                padding: 20px;
                min-height: 100vh;
            }
            .container {
                max-width: 1200px;
                margin: 0 auto;
            }
            .header {
                background: rgba(255, 255, 255, 0.95);
                border-radius: 20px;
                padding: 30px;
                margin-bottom: 30px;
                text-align: center;
                box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            }
            .stats {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 20px;
                margin-bottom: 30px;
            }
            .stat-card {
                background: white;
                border-radius: 15px;
                padding: 25px;
                text-align: center;
                box-shadow: 0 10px 20px rgba(0,0,0,0.05);
                transition: transform 0.3s;
            }
            .stat-card:hover {
                transform: translateY(-5px);
            }
            .stat-value {
                font-size: 2.5rem;
                font-weight: bold;
                margin: 10px 0;
                color: #4a5568;
            }
            .stat-label {
                color: #718096;
                font-size: 0.9rem;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            .signals-container {
                background: white;
                border-radius: 20px;
                padding: 30px;
                margin-bottom: 30px;
                box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            }
            .signal-card {
                padding: 20px;
                margin: 15px 0;
                border-radius: 12px;
                border-left: 5px solid;
                background: #f7fafc;
            }
            .signal-buy {
                border-left-color: #48bb78;
                background: #f0fff4;
            }
            .signal-sell {
                border-left-color: #f56565;
                background: #fff5f5;
            }
            .btn {
                display: inline-block;
                padding: 14px 28px;
                margin: 10px;
                border: none;
                border-radius: 12px;
                font-weight: 600;
                text-decoration: none;
                cursor: pointer;
                transition: all 0.3s;
            }
            .btn-primary {
                background: #4299e1;
                color: white;
            }
            .btn-danger {
                background: #f56565;
                color: white;
            }
            .btn-success {
                background: #48bb78;
                color: white;
            }
            .btn:hover {
                transform: translateY(-2px);
                box-shadow: 0 10px 20px rgba(0,0,0,0.1);
            }
            .pairs-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                gap: 15px;
                margin: 20px 0;
            }
            .pair-badge {
                background: #edf2f7;
                padding: 12px;
                border-radius: 10px;
                text-align: center;
                font-weight: 600;
            }
            .footer {
                text-align: center;
                color: white;
                margin-top: 40px;
                opacity: 0.8;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <!-- Header -->
            <div class="header">
                <h1 style="font-size: 2.5rem; margin: 0 0 10px 0; color: #2d3748;">
                    🤖 Crypto Signal Bot
                </h1>
                <p style="color: #718096; margin-bottom: 20px;">
                    Sistema automatizado de sinais de trading
                </p>
                
                <div style="margin: 20px 0;">
                    {% if not paused %}
                    <a href="/pause" class="btn btn-danger">
                        ⏸️ Pausar Bot
                    </a>
                    {% else %}
                    <a href="/resume" class="btn btn-success">
                        ▶️ Retomar Bot
                    </a>
                    {% endif %}
                    <a href="/check" class="btn btn-primary">
                        🔍 Verificar Agora
                    </a>
                </div>
            </div>
            
            <!-- Stats -->
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-label">Pares Monitorados</div>
                    <div class="stat-value">{{ pairs_count }}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Sinais Hoje</div>
                    <div class="stat-value">{{ today_signals }}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Buy/Sell</div>
                    <div class="stat-value">{{ buy_signals }}/{{ sell_signals }}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Uptime</div>
                    <div class="stat-value">{{ uptime_str }}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Status</div>
                    <div class="stat-value" style="color: {{ status_color }}">
                        {{ status_text }}
                    </div>
                </div>
            </div>
            
            <!-- Pares Monitorados -->
            <div class="signals-container">
                <h2 style="margin-top: 0; color: #2d3748;">📊 Pares Monitorados</h2>
                <div class="pairs-grid">
                    {% for pair in pairs %}
                    <div class="pair-badge">
                        {{ pair }}
                    </div>
                    {% endfor %}
                </div>
            </div>
            
            <!-- Sinais Recentes -->
            <div class="signals-container">
                <h2 style="margin-top: 0; color: #2d3748;">📈 Sinais Recentes</h2>
                
                {% if recent_signals %}
                    {% for signal in recent_signals %}
                    <div class="signal-card signal-{{ signal.direction|lower }}">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div>
                                <strong style="font-size: 1.2rem;">{{ signal.symbol }}</strong>
                                <span style="margin-left: 10px; padding: 4px 12px; background: {{ 'rgba(72, 187, 120, 0.1)' if signal.direction == 'BUY' else 'rgba(245, 101, 101, 0.1)' }}; color: {{ '#48bb78' if signal.direction == 'BUY' else '#f56565' }}; border-radius: 20px; font-weight: 600;">
                                    {{ signal.direction }}
                                </span>
                            </div>
                            <div style="color: #718096; font-size: 0.9rem;">
                                {{ signal.time.strftime('%H:%M') }}
                            </div>
                        </div>
                        <div style="margin-top: 10px; color: #4a5568;">
                            💰 ${{ "%.4f"|format(signal.price) }}
                            <span style="margin-left: 15px;">🎯 Conf: {{ "%.1f"|format(signal.score) }}/3.0</span>
                        </div>
                        {% if signal.strategies %}
                        <div style="margin-top: 5px; font-size: 0.9rem; color: #718096;">
                            📊 {{ signal.strategies|join(', ') }}
                        </div>
                        {% endif %}
                    </div>
                    {% endfor %}
                {% else %}
                    <div style="text-align: center; padding: 40px; color: #a0aec0;">
                        <div style="font-size: 4rem; margin-bottom: 20px;">📭</div>
                        <p style="font-size: 1.2rem;">Nenhum sinal gerado ainda</p>
                        <p>Os sinais aparecerão aqui quando o bot identificar oportunidades</p>
                    </div>
                {% endif %}
            </div>
            
            <!-- Footer -->
            <div class="footer">
                <p>🔄 Atualiza automaticamente a cada 60 segundos</p>
                <p>⚡ Powered by Render.com | 🐍 Python | 🤖 Telegram Bot</p>
                <p style="font-size: 0.9rem; margin-top: 10px;">
                    Última verificação: {{ current_time }}
                </p>
            </div>
        </div>
        
        <script>
            // Auto-refresh a cada 60 segundos
            setTimeout(function() {
                location.reload();
            }, 60000);
            
            // Confirmação para ações
            document.querySelectorAll('a[href*="pause"], a[href*="resume"]').forEach(link => {
                link.addEventListener('click', function(e) {
                    if (!confirm('Tem certeza que deseja ' + (this.href.includes('pause') ? 'pausar' : 'retomar') + ' o bot?')) {
                        e.preventDefault();
                    }
                });
            });
            
            // Animações simples
            document.addEventListener('DOMContentLoaded', function() {
                const cards = document.querySelectorAll('.stat-card, .signal-card');
                cards.forEach((card, index) => {
                    card.style.opacity = '0';
                    card.style.transform = 'translateY(20px)';
                    
                    setTimeout(() => {
                        card.style.transition = 'opacity 0.5s, transform 0.5s';
                        card.style.opacity = '1';
                        card.style.transform = 'translateY(0)';
                    }, index * 100);
                });
            });
        </script>
    </body>
    </html>
    '''
    
    # Sinais de hoje
    today = datetime.now().date()
    today_signals = [s for s in last_signals if s['time'].date() == today]
    buy_signals = len([s for s in today_signals if s['direction'] == 'BUY'])
    sell_signals = len([s for s in today_signals if s['direction'] == 'SELL'])
    
    # Sinais recentes (últimas 5 horas)
    recent_signals = [s for s in last_signals if s['time'] > datetime.now() - timedelta(hours=5)]
    recent_signals.sort(key=lambda x: x['time'], reverse=True)
    
    return render_template_string(
        html,
        pairs_count=len(PAIRS),
        today_signals=len(today_signals),
        buy_signals=buy_signals,
        sell_signals=sell_signals,
        uptime_str=f"{hours}h {minutes}m",
        status_text="ATIVO" if not signals_paused else "PAUSADO",
        status_color="#48bb78" if not signals_paused else "#f56565",
        pairs=PAIRS,
        recent_signals=recent_signals[:10],  # Apenas últimos 10
        paused=signals_paused,
        current_time=datetime.now().strftime('%H:%M:%S')
    )

@app.route('/pause')
def pause():
    """Pausa o bot"""
    global signals_paused
    signals_paused = True
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
            }
            .message {
                background: white;
                padding: 50px;
                border-radius: 20px;
                text-align: center;
                box-shadow: 0 20px 40px rgba(0,0,0,0.2);
                max-width: 500px;
            }
            h1 {
                color: #2d3748;
                margin-bottom: 20px;
            }
            p {
                color: #718096;
                margin-bottom: 30px;
            }
            .btn {
                display: inline-block;
                padding: 14px 28px;
                background: #4299e1;
                color: white;
                text-decoration: none;
                border-radius: 12px;
                font-weight: 600;
            }
        </style>
    </head>
    <body>
        <div class="message">
            <h1>⏸️ Bot Pausado</h1>
            <p>O sistema de sinais foi pausado com sucesso.</p>
            <a href="/" class="btn">Voltar ao Dashboard</a>
        </div>
    </body>
    </html>
    '''

@app.route('/resume')
def resume():
    """Retoma o bot"""
    global signals_paused
    signals_paused = False
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
            }
            .message {
                background: white;
                padding: 50px;
                border-radius: 20px;
                text-align: center;
                box-shadow: 0 20px 40px rgba(0,0,0,0.2);
                max-width: 500px;
            }
            h1 {
                color: #2d3748;
                margin-bottom: 20px;
            }
            p {
                color: #718096;
                margin-bottom: 30px;
            }
            .btn {
                display: inline-block;
                padding: 14px 28px;
                background: #48bb78;
                color: white;
                text-decoration: none;
                border-radius: 12px;
                font-weight: 600;
            }
        </style>
    </head>
    <body>
        <div class="message">
            <h1>▶️ Bot Retomado</h1>
            <p>O sistema de sinais foi reativado com sucesso.</p>
            <a href="/" class="btn">Voltar ao Dashboard</a>
        </div>
    </body>
    </html>
    '''

@app.route('/check')
def manual_check():
    """Verificação manual"""
    check_market()
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
            }
            .message {
                background: white;
                padding: 50px;
                border-radius: 20px;
                text-align: center;
                box-shadow: 0 20px 40px rgba(0,0,0,0.2);
                max-width: 500px;
            }
            h1 {
                color: #2d3748;
                margin-bottom: 20px;
            }
            p {
                color: #718096;
                margin-bottom: 30px;
            }
            .btn {
                display: inline-block;
                padding: 14px 28px;
                background: #4299e1;
                color: white;
                text-decoration: none;
                border-radius: 12px;
                font-weight: 600;
            }
        </style>
    </head>
    <body>
        <div class="message">
            <h1>🔍 Verificação Manual</h1>
            <p>O mercado está sendo verificado agora. Verifique o Telegram para sinais.</p>
            <a href="/" class="btn">Voltar ao Dashboard</a>
        </div>
    </body>
    </html>
    '''

@app.route('/health')
def health():
    """Endpoint de saúde"""
    return {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'pairs_monitored': len(PAIRS),
        'signals_today': len([s for s in last_signals if s['time'].date() == datetime.now().date()]),
        'bot_status': 'paused' if signals_paused else 'running',
        'uptime': str(datetime.now() - bot_start_time)
    }

# =========================
# LOOP PRINCIPAL
# =========================
def run_bot():
    """Loop principal do bot"""
    logger.info("🤖 Iniciando Crypto Signal Bot")
    logger.info(f"📊 Pares monitorados: {len(PAIRS)}")
    logger.info(f"🌐 Dashboard: disponível")
    
    # Envia mensagem de início
    if TELEGRAM_TOKEN and CHAT_ID:
        startup_msg = (
            "🚀 <b>CRYPTO SIGNAL BOT INICIADO</b>\n\n"
            f"📊 <b>Configuração:</b>\n"
            f"• Pares: {len(PAIRS)}\n"
            f"• Estratégias: RSI, EMA, Volume\n"
            f"• Intervalo: 1 minuto\n\n"
            f"🌐 Dashboard disponível\n"
            f"✅ Sistema operacional!"
        )
        send_telegram_message(startup_msg)
    
    # Loop principal
    check_interval = 60  # 1 minuto
    
    while True:
        if not signals_paused:
            check_market()
        
        time.sleep(check_interval)

# =========================
# INICIALIZAÇÃO
# =========================
def main():
    """Função principal"""
    
    # Inicia bot em thread separada
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Inicia servidor web
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"🌐 Iniciando servidor na porta {port}")
    app.run(host='0.0.0.0', port=port, debug=False)

if __name__ == "__main__":
    main()
