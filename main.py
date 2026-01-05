import os
import time
import threading
import requests
import json
from datetime import datetime
from flask import Flask, jsonify
import logging

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
BOT_INTERVAL = int(os.getenv("BOT_INTERVAL", "600"))  # 10 minutos
PORT = int(os.getenv("PORT", "10000"))

# Dados
signals = []
last_check = None

# =========================
# API ALTERNATIVAS (não bloqueadas pelo Render)
# =========================
def get_crypto_data(symbol):
    """Usa API pública alternativa que não é bloqueada"""
    
    # Mapear símbolos para diferentes APIs
    apis_to_try = [
        # 1. CoinGecko API (mais confiável, não bloqueada)
        {
            "name": "CoinGecko",
            "url": f"https://api.coingecko.com/api/v3/simple/price?ids={get_coingecko_id(symbol)}&vs_currencies=usd",
            "parser": lambda data, sym: data.get(get_coingecko_id(sym), {}).get("usd")
        },
        
        # 2. CoinMarketCap (via API pública)
        {
            "name": "CoinMarketCap",
            "url": f"https://api.coinmarketcap.com/data-api/v3/cryptocurrency/detail?slug={get_cmc_slug(symbol)}",
            "parser": lambda data, sym: data.get("data", {}).get("statistics", {}).get("price")
        },
        
        # 3. Binance via proxy público
        {
            "name": "Binance Proxy",
            "url": f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}",
            "parser": lambda data, sym: float(data.get("price", 0)) if data.get("price") else None
        },
        
        # 4. CryptoCompare
        {
            "name": "CryptoCompare", 
            "url": f"https://min-api.cryptocompare.com/data/price?fsym={symbol.replace("USDT", "")}&tsyms=USD",
            "parser": lambda data, sym: data.get("USD")
        }
    ]
    
    for api in apis_to_try:
        try:
            logger.info(f"Tentando {api['name']} para {symbol}")
            
            # Headers para parecer navegador
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json',
            }
            
            response = requests.get(api["url"], headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                price = api["parser"](data, symbol)
                
                if price:
                    logger.info(f"✅ {api['name']}: {symbol} = ${price}")
                    return float(price)
                    
        except Exception as e:
            logger.warning(f"❌ {api['name']} falhou: {str(e)[:50]}")
            continue
    
    logger.error(f"❌ Todas APIs falharam para {symbol}")
    return None

def get_coingecko_id(symbol):
    """Converte símbolo para ID do CoinGecko"""
    mapping = {
        "BTCUSDT": "bitcoin",
        "ETHUSDT": "ethereum", 
        "BNBUSDT": "binancecoin",
        "SOLUSDT": "solana",
        "XRPUSDT": "ripple",
        "ADAUSDT": "cardano",
        "DOGEUSDT": "dogecoin"
    }
    return mapping.get(symbol, symbol.replace("USDT", "").lower())

def get_cmc_slug(symbol):
    """Converte símbolo para slug do CoinMarketCap"""
    mapping = {
        "BTCUSDT": "bitcoin",
        "ETHUSDT": "ethereum",
        "BNBUSDT": "bnb",
        "SOLUSDT": "solana",
        "XRPUSDT": "xrp",
        "ADAUSDT": "cardano",
        "DOGEUSDT": "dogecoin"
    }
    return mapping.get(symbol, symbol.replace("USDT", "").lower())

# =========================
# ANÁLISE SIMPLES
# =========================
def analyze_crypto(symbol):
    """Análise básica"""
    try:
        # Pegar preço atual
        current_price = get_crypto_data(symbol)
        if current_price is None:
            return None
        
        # Simular análise (em produção, você pegaria dados históricos)
        # Para simplificar, vamos usar lógica baseada apenas no preço atual
        
        # Pares para comparação
        pairs = {
            "BTCUSDT": {"support": 40000, "resistance": 45000},
            "ETHUSDT": {"support": 2200, "resistance": 2500},
            "BNBUSDT": {"support": 300, "resistance": 350}
        }
        
        if symbol in pairs:
            levels = pairs[symbol]
            
            signal = None
            
            if current_price <= levels["support"] * 1.02:  # Próximo do suporte
                signal = {
                    "symbol": symbol,
                    "direction": "COMPRA",
                    "price": current_price,
                    "reason": f"Próximo do suporte (${levels['support']})",
                    "confidence": 0.7
                }
            elif current_price >= levels["resistance"] * 0.98:  # Próximo da resistência
                signal = {
                    "symbol": symbol,
                    "direction": "VENDA",
                    "price": current_price,
                    "reason": f"Próximo da resistência (${levels['resistance']})",
                    "confidence": 0.7
                }
            
            if signal:
                signal["timestamp"] = datetime.now().strftime("%H:%M:%S")
                signal["date"] = datetime.now().strftime("%d/%m/%Y")
                return signal
                
    except Exception as e:
        logger.error(f"Erro analisando {symbol}: {e}")
    
    return None

# =========================
# TELEGRAM
# =========================
def send_telegram_message(text):
    """Envia mensagem para Telegram"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return False
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "Markdown"
        }
        
        response = requests.post(url, json=data, timeout=10)
        return response.status_code == 200
    except:
        return False

# =========================
# ROTAS WEB
# =========================
@app.route('/')
def home():
    """Página inicial"""
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Crypto Bot - API Alternativa</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                color: white;
            }}
            .container {{
                background: rgba(255,255,255,0.1);
                backdrop-filter: blur(10px);
                border-radius: 20px;
                padding: 30px;
                margin-top: 20px;
            }}
            .status {{
                display: inline-block;
                padding: 10px 20px;
                background: #28a745;
                border-radius: 20px;
                font-weight: bold;
                margin-bottom: 20px;
            }}
            .card {{
                background: rgba(255,255,255,0.9);
                color: #333;
                padding: 20px;
                border-radius: 10px;
                margin-bottom: 15px;
            }}
            .signal {{
                border-left: 5px solid;
                padding-left: 15px;
                margin-bottom: 10px;
            }}
            .buy {{ border-color: #28a745; }}
            .sell {{ border-color: #dc3545; }}
            .price {{ 
                font-size: 24px; 
                font-weight: bold;
                color: #ffd700;
            }}
            .test-btn {{
                display: inline-block;
                padding: 10px 20px;
                background: #007bff;
                color: white;
                text-decoration: none;
                border-radius: 5px;
                margin: 5px;
            }}
        </style>
    </head>
    <body>
        <h1>🤖 Crypto Bot (API Alternativa)</h1>
        <p>Usando APIs públicas não bloqueadas pelo Render</p>
        
        <div class="status">● ONLINE</div>
        
        <div class="container">
            <h2>📊 Status do Sistema</h2>
            
            <div class="card">
                <h3>Testar Conexões</h3>
                <p>
                    <a class="test-btn" href="/test/btc">Testar BTC</a>
                    <a class="test-btn" href="/test/eth">Testar ETH</a>
                    <a class="test-btn" href="/test/bnb">Testar BNB</a>
                </p>
            </div>
            
            <div class="card">
                <h3>📈 Preços Atuais</h3>
                <div id="prices">Carregando preços...</div>
            </div>
            
            <div class="card">
                <h3>🎯 Últimos Sinais ({len(signals)})</h3>
                {"".join([f'''
                <div class="signal {s['direction'].lower()}">
                    <strong>{s['direction']} {s['symbol']}</strong><br>
                    <span class="price">${s['price']:.2f}</span><br>
                    {s['reason']}<br>
                    <small>{s['timestamp']}</small>
                </div>
                ''' for s in signals[-5:]]) or '<p>Nenhum sinal ainda...</p>'}
            </div>
            
            <div class="card">
                <h3>⚙️ Configuração</h3>
                <p><strong>Intervalo:</strong> {BOT_INTERVAL//60} minutos</p>
                <p><strong>Última verificação:</strong> {last_check or "Nunca"}</p>
                <p><strong>Telegram:</strong> {'✅ Configurado' if TELEGRAM_TOKEN else '❌ Não configurado'}</p>
            </div>
            
            <div class="card">
                <h3>🔗 Links Úteis</h3>
                <p>
                    <a class="test-btn" href="/health">Health Check</a>
                    <a class="test-btn" href="/api/prices">API Preços</a>
                    <a class="test-btn" href="/manual-check">Verificar Agora</a>
                </p>
            </div>
        </div>
        
        <script>
            // Atualizar preços automaticamente
            async function updatePrices() {{
                try {{
                    const response = await fetch('/api/prices');
                    const data = await response.json();
                    
                    let html = '';
                    for (const [symbol, price] of Object.entries(data.prices)) {{
                        html += `<div>${{symbol}}: <span class="price">$${{price.toFixed(2)}}</span></div>`;
                    }}
                    
                    document.getElementById('prices').innerHTML = html;
                }} catch (e) {{
                    document.getElementById('prices').innerHTML = 'Erro ao carregar preços';
                }}
            }}
            
            // Atualizar a cada 30 segundos
            updatePrices();
            setInterval(updatePrices, 30000);
            
            // Auto-refresh da página a cada 2 minutos
            setTimeout(() => location.reload(), 120000);
        </script>
    </body>
    </html>
    """
    return html

@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "crypto-bot-alt-api",
        "version": "1.0"
    })

@app.route('/test/<symbol>')
def test_symbol(symbol):
    """Testa um símbolo específico"""
    sym = symbol.upper() + "USDT"
    price = get_crypto_data(sym)
    
    if price:
        return jsonify({
            "status": "success",
            "symbol": sym,
            "price": price,
            "message": "API funcionando!"
        })
    else:
        return jsonify({
            "status": "error",
            "symbol": sym,
            "message": "Falha em todas APIs"
        })

@app.route('/api/prices')
def api_prices():
    """API para preços atuais"""
    prices = {}
    for symbol in ["BTCUSDT", "ETHUSDT", "BNBUSDT"]:
        price = get_crypto_data(symbol)
        if price:
            prices[symbol] = price
    
    return jsonify({
        "prices": prices,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/manual-check')
def manual_check():
    """Verificação manual"""
    try:
        # Verificar os 3 principais pares
        results = {}
        for symbol in ["BTCUSDT", "ETHUSDT", "BNBUSDT"]:
            price = get_crypto_data(symbol)
            results[symbol] = price or 0
        
        return jsonify({
            "status": "success",
            "results": results,
            "message": "Verificação concluída"
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        })

# =========================
# BOT WORKER
# =========================
def bot_worker():
    """Worker principal"""
    logger.info("🤖 Bot iniciado com APIs alternativas")
    
    # Pares a monitorar
    pairs = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
    
    # Mensagem inicial
    if TELEGRAM_TOKEN and CHAT_ID:
        send_telegram_message(
            f"🤖 *Crypto Bot Iniciado*\n"
            f"Usando APIs alternativas\n"
            f"Monitorando {len(pairs)} pares\n"
            f"Intervalo: {BOT_INTERVAL//60} minutos\n"
            f"✅ Pronto para operar!"
        )
    
    while True:
        try:
            global last_check, signals
            last_check = datetime.now().strftime("%H:%M:%S")
            
            logger.info(f"🔍 Iniciando verificação...")
            
            for symbol in pairs:
                # Analisar
                signal = analyze_crypto(symbol)
                
                if signal:
                    logger.info(f"📢 Sinal: {signal['direction']} {signal['symbol']} ${signal['price']:.2f}")
                    
                    # Adicionar à lista
                    signals.append(signal)
                    if len(signals) > 15:
                        signals.pop(0)
                    
                    # Enviar para Telegram
                    if TELEGRAM_TOKEN and CHAT_ID:
                        message = (
                            f"🎯 *{signal['direction']} ALERT*\n"
                            f"💰 {signal['symbol']}\n"
                            f"💵 Preço: ${signal['price']:.2f}\n"
                            f"📈 {signal['reason']}\n"
                            f"⏰ {signal['timestamp']}\n"
                            f"📅 {signal['date']}\n\n"
                            f"#CryptoAlert #{signal['symbol'].replace('USDT', '')}"
                        )
                        send_telegram_message(message)
                        time.sleep(1)  # Pausa entre mensagens
                
                time.sleep(3)  # Pausa entre pares
            
            logger.info(f"✅ Verificação completa. Próxima em {BOT_INTERVAL//60} minutos")
            time.sleep(BOT_INTERVAL)
            
        except Exception as e:
            logger.error(f"❌ Erro no worker: {e}")
            time.sleep(60)

# =========================
# INICIAR
# =========================
def main():
    """Função principal"""
    logger.info(f"🚀 Iniciando Crypto Bot na porta {PORT}")
    
    # Iniciar worker em thread separada
    thread = threading.Thread(target=bot_worker, daemon=True)
    thread.start()
    
    # Iniciar servidor Flask
    app.run(
        host='0.0.0.0',
        port=PORT,
        debug=False,
        use_reloader=False
    )

if __name__ == '__main__':
    main()
