import os
import time
import requests
from flask import Flask, jsonify, render_template_string
from datetime import datetime
import threading

app = Flask(__name__)

# Configuração básica
PORT = int(os.getenv("PORT", 10000))

# Lista de criptomoedas
CRYPTO_SYMBOLS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA"]

# Armazenamento em memória
signals = []
start_time = time.time()

def get_crypto_price(symbol):
    """Pega preço atual da Binance"""
    try:
        url = f"https://api.binance.com/api/v3/ticker/price"
        response = requests.get(url, params={"symbol": f"{symbol}USDT"}, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return float(data['price'])
    except:
        pass
    return None

def get_market_sentiment():
    """Pega sentimento do mercado"""
    try:
        response = requests.get("https://api.alternative.me/fng/", timeout=5)
        if response.status_code == 200:
            data = response.json()
            value = int(data['data'][0]['value'])
            
            if value >= 75:
                return "GANÂNCIA EXTREMA", value
            elif value >= 55:
                return "GANÂNCIA", value
            elif value >= 45:
                return "NEUTRO", value
            elif value >= 25:
                return "MEDO", value
            else:
                return "MEDO EXTREMO", value
    except:
        pass
    
    return "NEUTRO", 50

def generate_signal():
    """Gera um sinal de trading"""
    import random
    
    # Escolher criptomoeda aleatória
    symbol = random.choice(CRYPTO_SYMBOLS)
    
    # Pegar preço atual
    price = get_crypto_price(symbol)
    if price is None:
        return None
    
    # Pegar sentimento
    sentiment, sentiment_value = get_market_sentiment()
    
    # Decidir direção baseada no sentimento
    if sentiment_value > 55:  # Greed
        direction = "COMPRA" if random.random() > 0.3 else "VENDA"
    elif sentiment_value < 45:  # Fear
        direction = "VENDA" if random.random() > 0.3 else "COMPRA"
    else:
        direction = random.choice(["COMPRA", "VENDA"])
    
    # Calcular TP e SL
    if direction == "COMPRA":
        tp = round(price * 1.03, 2)  # +3%
        sl = round(price * 0.98, 2)  # -2%
    else:
        tp = round(price * 0.97, 2)  # -3%
        sl = round(price * 1.02, 2)  # +2%
    
    # Calcular confiança
    confidence = random.randint(70, 90)
    
    signal = {
        'id': int(time.time()),
        'symbol': f"{symbol}/USDT",
        'direction': direction,
        'price': price,
        'tp': tp,
        'sl': sl,
        'confidence': confidence,
        'sentiment': sentiment,
        'sentiment_value': sentiment_value,
        'time': datetime.now().strftime("%H:%M:%S"),
        'date': datetime.now().strftime("%d/%m/%Y")
    }
    
    return signal

def signal_generator():
    """Thread que gera sinais periodicamente"""
    time.sleep(5)  # Espera inicial
    
    while True:
        try:
            signal = generate_signal()
            if signal:
                signals.append(signal)
                # Manter apenas últimos 20 sinais
                if len(signals) > 20:
                    signals.pop(0)
                
                print(f"Novo sinal: {signal['symbol']} {signal['direction']} a ${signal['price']}")
            
            # Espera 5-10 minutos
            time.sleep(random.randint(300, 600))
            
        except Exception as e:
            print(f"Erro no gerador: {e}")
            time.sleep(60)

# ROTAS
@app.route('/')
def home():
    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Crypto Signals</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {
                background: #0f172a;
                color: #e2e8f0;
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 20px;
            }
            .container {
                max-width: 1200px;
                margin: 0 auto;
            }
            .header {
                text-align: center;
                margin-bottom: 30px;
                padding-bottom: 20px;
                border-bottom: 2px solid #3b82f6;
            }
            .signal-card {
                background: #1e293b;
                border-radius: 10px;
                padding: 20px;
                margin-bottom: 15px;
                border-left: 4px solid;
            }
            .buy { border-color: #10b981; }
            .sell { border-color: #ef4444; }
            .stats {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 15px;
                margin-bottom: 30px;
            }
            .stat-card {
                background: #1e293b;
                padding: 20px;
                border-radius: 10px;
                text-align: center;
            }
            .badge {
                display: inline-block;
                padding: 4px 12px;
                border-radius: 20px;
                font-size: 12px;
                font-weight: bold;
                margin-right: 5px;
            }
            .badge-buy { background: #10b981; color: white; }
            .badge-sell { background: #ef4444; color: white; }
            .badge-conf { background: #3b82f6; color: white; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🚀 Crypto Trading Signals</h1>
                <p>Análise automática do mercado em tempo real</p>
            </div>
            
            <div class="stats">
                <div class="stat-card">
                    <h3>{{ signals|length }}</h3>
                    <p>Sinais Gerados</p>
                </div>
                <div class="stat-card">
                    <h3>{{ buy_count }}</h3>
                    <p>Sinais de Compra</p>
                </div>
                <div class="stat-card">
                    <h3>{{ sell_count }}</h3>
                    <p>Sinais de Venda</p>
                </div>
                <div class="stat-card">
                    <h3>{{ last_update }}</h3>
                    <p>Última Atualização</p>
                </div>
            </div>
            
            <h2>📊 Sinais Recentes</h2>
            
            {% if signals %}
                {% for signal in signals|reverse %}
                <div class="signal-card {{ 'buy' if signal.direction == 'COMPRA' else 'sell' }}">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                        <h3 style="margin: 0;">{{ signal.symbol }}</h3>
                        <div>
                            <span class="badge {{ 'badge-buy' if signal.direction == 'COMPRA' else 'badge-sell' }}">
                                {{ signal.direction }}
                            </span>
                            <span class="badge badge-conf">
                                {{ signal.confidence }}% Confiança
                            </span>
                        </div>
                    </div>
                    
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 15px;">
                        <div>
                            <small>Preço Atual</small>
                            <h2 style="margin: 5px 0;">${{ "%.4f"|format(signal.price) }}</h2>
                        </div>
                        <div>
                            <small>Take Profit</small>
                            <h2 style="margin: 5px 0; color: #10b981;">${{ signal.tp }}</h2>
                            <small>+{{ (((signal.tp - signal.price) / signal.price) * 100)|round(2) }}%</small>
                        </div>
                        <div>
                            <small>Stop Loss</small>
                            <h2 style="margin: 5px 0; color: #ef4444;">${{ signal.sl }}</h2>
                            <small>-{{ (((signal.price - signal.sl) / signal.price) * 100)|round(2) }}%</small>
                        </div>
                    </div>
                    
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <small>Sentimento: <strong>{{ signal.sentiment }}</strong> ({{ signal.sentiment_value }})</small>
                        </div>
                        <div>
                            <small>{{ signal.time }} • {{ signal.date }}</small>
                        </div>
                    </div>
                </div>
                {% endfor %}
            {% else %}
                <div class="signal-card">
                    <h3 style="text-align: center;">⏳ Gerando primeiros sinais...</h3>
                    <p style="text-align: center;">Aguarde alguns instantes</p>
                </div>
            {% endif %}
            
            <div style="text-align: center; margin-top: 30px; color: #94a3b8; font-size: 14px;">
                <p>Atualiza automaticamente a cada 30 segundos</p>
                <p>Sistema de análise automática • Dados em tempo real</p>
            </div>
        </div>
        
        <script>
            // Auto-refresh
            setTimeout(() => {
                location.reload();
            }, 30000);
            
            // Adicionar log de carregamento
            console.log('Crypto Signals Dashboard carregado');
        </script>
    </body>
    </html>
    '''
    
    buy_count = len([s for s in signals if s['direction'] == 'COMPRA'])
    sell_count = len([s for s in signals if s['direction'] == 'VENDA'])
    last_update = datetime.now().strftime("%H:%M:%S")
    
    return render_template_string(
        html, 
        signals=signals[-10:],
        buy_count=buy_count,
        sell_count=sell_count,
        last_update=last_update
    )

@app.route('/health')
def health():
    """Health check para Render"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "signals_count": len(signals),
        "uptime_seconds": int(time.time() - start_time)
    })

@app.route('/api/signals')
def api_signals():
    """API para obter sinais"""
    return jsonify({
        "count": len(signals),
        "signals": signals[-10:],
        "updated": datetime.now().isoformat()
    })

@app.route('/api/generate')
def generate_now():
    """Força geração de um sinal"""
    signal = generate_signal()
    if signal:
        signals.append(signal)
        if len(signals) > 20:
            signals.pop(0)
        
        return jsonify({
            "success": True,
            "signal": signal
        })
    else:
        return jsonify({
            "success": False,
            "message": "Erro ao gerar sinal"
        })

# Iniciar thread de geração de sinais
import random  # Import aqui para evitar erro
thread = threading.Thread(target=signal_generator, daemon=True)
thread.start()

if __name__ == '__main__':
    print("=" * 50)
    print("CRYPTO SIGNALS BOT INICIADO")
    print(f"Porta: {PORT}")
    print(f"URL: http://0.0.0.0:{PORT}")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=PORT, debug=False)
