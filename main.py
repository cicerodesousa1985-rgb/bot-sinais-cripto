import os
import time
import threading
import requests
from datetime import datetime
from flask import Flask, jsonify
import logging

# =========================
# CONFIGURAÇÃO SIMPLES
# =========================
app = Flask(__name__)

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configurações (use variáveis de ambiente no Render)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
BOT_INTERVAL = int(os.getenv("BOT_INTERVAL", "300"))  # 5 minutos
PORT = int(os.getenv("PORT", "10000"))

# Dados simples em memória
signals = []
last_check = None

# =========================
# FUNÇÃO SIMPLIFICADA PARA BINANCE
# =========================
def get_binance_price(symbol):
    """Busca apenas o preço atual - mais simples e confiável"""
    try:
        # Usar endpoint mais simples
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            return float(data['price'])
        else:
            logger.warning(f"Erro {response.status_code} para {symbol}")
            return None
            
    except Exception as e:
        logger.error(f"Falha ao buscar {symbol}: {str(e)[:50]}")
        return None

def get_binance_klines_simple(symbol, interval="15m", limit=10):
    """Versão ultra simplificada"""
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
        
        # Timeout curto
        response = requests.get(url, params=params, timeout=8)
        
        if response.status_code == 200:
            return response.json()
        return None
        
    except:
        return None

# =========================
# ANÁLISE SUPER SIMPLES
# =========================
def analyze_simple(symbol):
    """Análise extremamente simplificada"""
    try:
        # 1. Pegar preço atual
        current_price = get_binance_price(symbol)
        if current_price is None:
            return None
        
        # 2. Pegar alguns candles
        klines = get_binance_klines_simple(symbol, "15m", 20)
        if not klines or len(klines) < 10:
            return None
        
        # 3. Calcular preços
        closes = [float(k[4]) for k in klines]
        
        # 4. Análise MUITO simples
        recent_high = max(closes[-10:])
        recent_low = min(closes[-10:])
        avg_price = sum(closes[-10:]) / 10
        
        signal = None
        
        # Condição 1: Preço muito abaixo da média
        if current_price < avg_price * 0.98:  # 2% abaixo
            signal = {
                "symbol": symbol,
                "direction": "COMPRA",
                "price": current_price,
                "reason": f"Preço ${current_price:.2f} está 2% abaixo da média",
                "confidence": 0.6
            }
        
        # Condição 2: Preço muito acima da média
        elif current_price > avg_price * 1.02:  # 2% acima
            signal = {
                "symbol": symbol,
                "direction": "VENDA", 
                "price": current_price,
                "reason": f"Preço ${current_price:.2f} está 2% acima da média",
                "confidence": 0.6
            }
        
        # Condição 3: Próximo de suporte/resistência
        elif current_price <= recent_low * 1.01:  # 1% acima do mínimo
            signal = {
                "symbol": symbol,
                "direction": "COMPRA",
                "price": current_price,
                "reason": f"Próximo do suporte (mínimo recente: ${recent_low:.2f})",
                "confidence": 0.7
            }
        
        elif current_price >= recent_high * 0.99:  # 1% abaixo do máximo
            signal = {
                "symbol": symbol,
                "direction": "VENDA",
                "price": current_price,
                "reason": f"Próximo da resistência (máximo recente: ${recent_high:.2f})",
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
# TELEGRAM SIMPLES
# =========================
def send_telegram_simple(message):
    """Envia para Telegram"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return False
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        
        response = requests.post(url, json=data, timeout=5)
        return response.status_code == 200
    except:
        return False

# =========================
# ROTAS WEB SIMPLES
# =========================
@app.route('/')
def home():
    """Página inicial simples"""
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Crypto Bot Simples</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
                background: #f0f2f5;
            }}
            .header {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 30px;
                border-radius: 10px;
                text-align: center;
                margin-bottom: 20px;
            }}
            .card {{
                background: white;
                padding: 20px;
                border-radius: 10px;
                margin-bottom: 15px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            .signal {{
                border-left: 4px solid;
                padding-left: 15px;
            }}
            .buy {{
                border-color: #28a745;
                background: #d4edda;
            }}
            .sell {{
                border-color: #dc3545;
                background: #f8d7da;
            }}
            .status {{
                display: inline-block;
                padding: 5px 10px;
                border-radius: 20px;
                font-weight: bold;
            }}
            .online {{
                background: #d4edda;
                color: #155724;
            }}
            .stats {{
                display: flex;
                gap: 15px;
                flex-wrap: wrap;
            }}
            .stat {{
                flex: 1;
                min-width: 150px;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🤖 Crypto Bot Simples</h1>
            <p>Monitoramento básico de criptomoedas</p>
            <div class="status online">● ONLINE</div>
        </div>
        
        <div class="stats">
            <div class="card stat">
                <h3>3</h3>
                <p>Pares monitorados</p>
            </div>
            <div class="card stat">
                <h3>{len(signals)}</h3>
                <p>Sinais gerados</p>
            </div>
            <div class="card stat">
                <h3>{BOT_INTERVAL}s</h3>
                <p>Intervalo</p>
            </div>
        </div>
        
        <div class="card">
            <h2>📊 Últimos Sinais</h2>
            {"".join([f'''
            <div class="signal {s['direction'].lower()}">
                <strong>{s['direction']} {s['symbol']}</strong><br>
                ${s['price']:.2f} - {s['reason']}<br>
                <small>{s['timestamp']}</small>
            </div>
            ''' for s in signals[-5:]]) or '<p>Nenhum sinal ainda...</p>'}
        </div>
        
        <div class="card">
            <p><strong>Par:</strong> BTCUSDT, ETHUSDT, BNBUSDT</p>
            <p><strong>Intervalo:</strong> A cada {BOT_INTERVAL//60} minutos</p>
            <p><strong>Última verificação:</strong> {last_check or "Nunca"}</p>
        </div>
        
        <div class="card">
            <p>
                <a href="/health">Health Check</a> | 
                <a href="/test">Testar API</a> | 
                <a href="/check">Verificar agora</a>
            </p>
        </div>
    </body>
    </html>
    """
    return html

@app.route('/health')
def health():
    """Health check simples"""
    return jsonify({
        "status": "healthy",
        "time": datetime.now().isoformat(),
        "service": "crypto-bot-simple",
        "signals": len(signals)
    })

@app.route('/test')
def test_api():
    """Testa conexão com Binance"""
    try:
        # Testar endpoint mais simples
        response = requests.get(
            "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
            timeout=5
        )
        
        if response.status_code == 200:
            price = float(response.json()['price'])
            return jsonify({
                "status": "success",
                "message": "API Binance funcionando!",
                "btc_price": price,
                "time": datetime.now().isoformat()
            })
        else:
            return jsonify({
                "status": "error",
                "code": response.status_code,
                "message": "Erro na API Binance"
            })
            
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        })

@app.route('/check')
def manual_check():
    """Verificação manual"""
    try:
        price = get_binance_price("BTCUSDT")
        if price:
            return jsonify({
                "status": "success",
                "btc_price": price,
                "message": "Conexão OK com Binance"
            })
        else:
            return jsonify({
                "status": "error",
                "message": "Falha ao conectar com Binance"
            })
    except:
        return jsonify({"status": "error"})

# =========================
# BOT WORKER SIMPLES
# =========================
def bot_worker():
    """Trabalhador do bot"""
    logger.info("🤖 Bot iniciado (versão simples)")
    
    # Pares a monitorar
    pairs = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
    
    while True:
        try:
            global last_check
            last_check = datetime.now().strftime("%H:%M:%S")
            
            logger.info(f"🔍 Verificando {len(pairs)} pares...")
            
            for symbol in pairs:
                # Análise simples
                signal = analyze_simple(symbol)
                
                if signal:
                    logger.info(f"📢 Sinal: {signal['direction']} {signal['symbol']}")
                    
                    # Adicionar à lista
                    signals.append(signal)
                    if len(signals) > 20:
                        signals.pop(0)
                    
                    # Enviar para Telegram
                    if TELEGRAM_TOKEN and CHAT_ID:
                        message = (
                            f"📊 *{signal['direction']} {signal['symbol']}*\n"
                            f"💵 Preço: ${signal['price']:.2f}\n"
                            f"📈 Motivo: {signal['reason']}\n"
                            f"⏰ Horário: {signal['timestamp']}"
                        )
                        send_telegram_simple(message)
                
                # Pequena pausa entre pares
                time.sleep(2)
            
            logger.info(f"✅ Verificação completa. Próxima em {BOT_INTERVAL//60} minutos")
            time.sleep(BOT_INTERVAL)
            
        except Exception as e:
            logger.error(f"❌ Erro: {e}")
            time.sleep(60)  # Esperar 1 minuto em caso de erro

# =========================
# INICIAR
# =========================
def main():
    """Função principal"""
    logger.info(f"🚀 Iniciando na porta {PORT}")
    
    # Iniciar bot em background
    thread = threading.Thread(target=bot_worker, daemon=True)
    thread.start()
    
    # Iniciar servidor
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

if __name__ == '__main__':
    main()
