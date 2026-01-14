import os
import time
import threading
import requests
import json
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from flask import Flask, render_template_string, jsonify, request
import logging
from collections import deque

# =========================
# CONFIGURAÇÃO
# =========================
app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configurações
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
PORT = int(os.getenv("PORT", "10000"))
DB_FILE = "historico_sinais.json"

# Lista de criptomoedas
CRYPTO_PAIRS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "MATIC"]

# Timeframes
TIMEFRAMES = ["15m", "1h"]

# Tempo de início
start_time = time.time()

# =========================
# FUNÇÕES DE ANÁLISE TÉCNICA
# =========================

def calcular_rsi(prices, period=14):
    """Calcula Relative Strength Index"""
    if len(prices) < period + 1:
        return np.full(len(prices), 50)
    
    deltas = np.diff(prices)
    seed = deltas[:period]
    
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    
    if down == 0:
        return np.full(len(prices), 100)
    
    rs = up / down
    rsi = np.zeros_like(prices)
    rsi[:period] = 100.0 - 100.0 / (1.0 + rs)
    
    for i in range(period, len(prices)):
        delta = deltas[i-1]
        
        if delta > 0:
            upval = delta
            downval = 0.0
        else:
            upval = 0.0
            downval = -delta
        
        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        
        if down == 0:
            rsi[i] = 100
        else:
            rs = up / down
            rsi[i] = 100.0 - 100.0 / (1.0 + rs)
    
    return rsi

def calcular_media_movel(prices, period):
    """Calcula média móvel simples"""
    return pd.Series(prices).rolling(window=period).mean()

def calcular_macd(prices):
    """Calcula MACD"""
    ema12 = pd.Series(prices).ewm(span=12, adjust=False).mean()
    ema26 = pd.Series(prices).ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line
    
    return macd_line.values, signal_line.values, histogram.values

def get_current_price(symbol):
    """Obtém preço atual da criptomoeda"""
    try:
        url = f"https://api.binance.com/api/v3/ticker/price"
        params = {"symbol": f"{symbol}USDT"}
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            return float(data['price'])
        else:
            # Fallback para CoinGecko
            url = f"https://api.coingecko.com/api/v3/simple/price"
            params = {"ids": symbol.lower(), "vs_currencies": "usd"}
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                return data[symbol.lower()]['usd']
    
    except Exception as e:
        logger.error(f"Erro ao buscar preço de {symbol}: {e}")
    
    return None

def get_historical_data(symbol, timeframe="15m", limit=50):
    """Obtém dados históricos"""
    try:
        # Mapeamento de timeframe para intervalo Binance
        interval_map = {
            "5m": "5m", "15m": "15m", "1h": "1h",
            "4h": "4h", "1d": "1d"
        }
        
        interval = interval_map.get(timeframe, "15m")
        url = "https://api.binance.com/api/v3/klines"
        
        params = {
            "symbol": f"{symbol}USDT",
            "interval": interval,
            "limit": limit
        }
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            if isinstance(data, list) and len(data) > 0:
                # Criar DataFrame
                closes = []
                highs = []
                lows = []
                volumes = []
                
                for candle in data:
                    closes.append(float(candle[4]))  # Preço de fechamento
                    highs.append(float(candle[2]))   # Máximo
                    lows.append(float(candle[3]))    # Mínimo
                    volumes.append(float(candle[5])) # Volume
                
                return {
                    'close': np.array(closes),
                    'high': np.array(highs),
                    'low': np.array(lows),
                    'volume': np.array(volumes)
                }
    
    except Exception as e:
        logger.error(f"Erro ao buscar dados históricos de {symbol}: {e}")
    
    return None

def analisar_cripto(symbol, timeframe="15m"):
    """Analisa uma criptomoeda e retorna sinal"""
    try:
        # Obter dados históricos
        data = get_historical_data(symbol, timeframe, limit=50)
        
        if data is None:
            return None
        
        close_prices = data['close']
        
        if len(close_prices) < 20:
            return None
        
        # Calcular indicadores
        rsi = calcular_rsi(close_prices)
        current_rsi = rsi[-1]
        
        sma20 = calcular_media_movel(close_prices, 20).iloc[-1]
        sma50 = calcular_media_movel(close_prices, 50).iloc[-1]
        
        macd_line, signal_line, _ = calcular_macd(close_prices)
        current_macd = macd_line[-1]
        current_signal = signal_line[-1]
        
        # Obter preço atual
        current_price = get_current_price(symbol)
        if current_price is None:
            return None
        
        # Análise técnica
        pontos_compra = 0
        pontos_venda = 0
        motivos = []
        
        # 1. RSI
        if current_rsi < 30:
            pontos_compra += 2
            motivos.append(f"RSI {current_rsi:.1f} (Oversold)")
        elif current_rsi > 70:
            pontos_venda += 2
            motivos.append(f"RSI {current_rsi:.1f} (Overbought)")
        
        # 2. Médias móveis
        if current_price > sma20 > sma50:
            pontos_compra += 1
            motivos.append("Tendência de Alta")
        elif current_price < sma20 < sma50:
            pontos_venda += 1
            motivos.append("Tendência de Baixa")
        
        # 3. MACD
        if current_macd > current_signal:
            pontos_compra += 1
        else:
            pontos_venda += 1
        
        # 4. Suporte/Resistência simples
        recent_low = np.min(close_prices[-10:])
        recent_high = np.max(close_prices[-10:])
        
        if current_price < recent_low * 1.02:  # Perto do suporte
            pontos_compra += 1
            motivos.append("Perto do Suporte")
        elif current_price > recent_high * 0.98:  # Perto da resistência
            pontos_venda += 1
            motivos.append("Perto da Resistência")
        
        # Determinar direção
        if pontos_compra > pontos_venda and pontos_compra >= 2:
            confianca = min(90, 50 + (pontos_compra * 10))
            return {
                'symbol': f"{symbol}USDT",
                'direction': "COMPRA",
                'price': current_price,
                'confidence': int(confianca),
                'reasons': motivos[:3],
                'timeframe': timeframe,
                'indicators': {
                    'rsi': round(current_rsi, 2),
                    'sma20': round(sma20, 4),
                    'sma50': round(sma50, 4),
                    'support': round(recent_low, 4),
                    'resistance': round(recent_high, 4)
                }
            }
        elif pontos_venda > pontos_compra and pontos_venda >= 2:
            confianca = min(90, 50 + (pontos_venda * 10))
            return {
                'symbol': f"{symbol}USDT",
                'direction': "VENDA",
                'price': current_price,
                'confidence': int(confianca),
                'reasons': motivos[:3],
                'timeframe': timeframe,
                'indicators': {
                    'rsi': round(current_rsi, 2),
                    'sma20': round(sma20, 4),
                    'sma50': round(sma50, 4),
                    'support': round(recent_low, 4),
                    'resistance': round(recent_high, 4)
                }
            }
    
    except Exception as e:
        logger.error(f"Erro analisando {symbol}: {e}")
    
    return None

def get_market_sentiment():
    """Obtém o sentimento do mercado"""
    try:
        # Fear & Greed Index
        response = requests.get("https://api.alternative.me/fng/", timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            value = int(data['data'][0]['value'])
            
            if value >= 75:
                return "GANÂNCIA EXTREMA", f"Fear & Greed: {value}"
            elif value >= 55:
                return "GANÂNCIA", f"Fear & Greed: {value}"
            elif value >= 45:
                return "NEUTRO", f"Fear & Greed: {value}"
            elif value >= 25:
                return "MEDO", f"Fear & Greed: {value}"
            else:
                return "MEDO EXTREMO", f"Fear & Greed: {value}"
    
    except Exception as e:
        logger.error(f"Erro ao buscar sentimento: {e}")
    
    return "NEUTRO", "Sem dados"

# =========================
# GESTÃO DE SINAIS
# =========================

class SignalManager:
    def __init__(self):
        self.signals = deque(maxlen=50)
        self.stats = {
            'total_signals': 0,
            'buy_signals': 0,
            'sell_signals': 0
        }
        self.load_signals()
    
    def load_signals(self):
        """Carrega sinais do arquivo"""
        try:
            if os.path.exists(DB_FILE):
                with open(DB_FILE, 'r') as f:
                    data = json.load(f)
                    self.signals = deque(data.get('signals', []), maxlen=50)
                    self.stats = data.get('stats', self.stats)
        except Exception as e:
            logger.error(f"Erro ao carregar sinais: {e}")
    
    def save_signals(self):
        """Salva sinais no arquivo"""
        try:
            data = {
                'signals': list(self.signals),
                'stats': self.stats,
                'last_update': datetime.now().isoformat()
            }
            
            with open(DB_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Erro ao salvar sinais: {e}")
    
    def add_signal(self, signal_data):
        """Adiciona um novo sinal"""
        if signal_data:
            signal = {
                'id': int(time.time()),
                'timestamp': datetime.now().isoformat(),
                'time': datetime.now().strftime("%H:%M:%S"),
                'date': datetime.now().strftime("%d/%m/%Y"),
                'data': signal_data
            }
            
            self.signals.append(signal)
            
            # Atualizar estatísticas
            self.stats['total_signals'] += 1
            if signal_data['direction'] == 'COMPRA':
                self.stats['buy_signals'] += 1
            else:
                self.stats['sell_signals'] += 1
            
            self.save_signals()
            
            # Enviar para Telegram
            self.send_telegram_signal(signal)
            
            return signal
        
        return None
    
    def send_telegram_signal(self, signal):
        """Envia sinal para Telegram"""
        if not TELEGRAM_TOKEN or not CHAT_ID:
            return
        
        try:
            data = signal['data']
            emoji = "🟢" if data['direction'] == 'COMPRA' else "🔴"
            
            message = f"""
{emoji} *SINAL DETECTADO*

*Par:* {data['symbol']}
*Direção:* {data['direction']}
*Preço:* ${data['price']:.4f}
*Confiança:* {data['confidence']}%
*Timeframe:* {data['timeframe']}

*Indicadores:*
• RSI: {data['indicators']['rsi']}
• SMA20: {data['indicators']['sma20']:.4f}
• SMA50: {data['indicators']['sma50']:.4f}

*Motivos:*
{chr(10).join(['• ' + r for r in data['reasons']])}

*Horário:* {signal['time']}
*Data:* {signal['date']}
"""
            
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {
                'chat_id': CHAT_ID,
                'text': message,
                'parse_mode': 'Markdown'
            }
            
            response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                logger.info("Sinal enviado para Telegram")
            else:
                logger.error(f"Erro ao enviar para Telegram: {response.text}")
        
        except Exception as e:
            logger.error(f"Erro no envio do Telegram: {e}")
    
    def get_recent_signals(self, limit=10):
        """Retorna sinais recentes"""
        return list(self.signals)[-limit:]

# Instância global
signal_manager = SignalManager()

# =========================
# BOT PRINCIPAL
# =========================

def analyze_market():
    """Analisa o mercado e gera sinais"""
    logger.info("Iniciando análise do mercado...")
    
    while True:
        try:
            # Obter sentimento do mercado
            sentiment, sentiment_msg = get_market_sentiment()
            
            # Analisar cada par
            signals_found = 0
            
            for symbol in CRYPTO_PAIRS:
                for timeframe in TIMEFRAMES:
                    try:
                        # Analisar criptomoeda
                        signal_data = analisar_cripto(symbol, timeframe)
                        
                        if signal_data:
                            # Adicionar sentimento ao sinal
                            signal_data['sentiment'] = sentiment
                            signal_data['sentiment_msg'] = sentiment_msg
                            
                            # Adicionar TP/SL baseado no risco
                            price = signal_data['price']
                            if signal_data['direction'] == 'COMPRA':
                                tp = price * 1.03  # 3% de lucro
                                sl = price * 0.98  # 2% de stop
                            else:
                                tp = price * 0.97  # 3% de lucro (short)
                                sl = price * 1.02  # 2% de stop
                            
                            signal_data['tp'] = round(tp, 4)
                            signal_data['sl'] = round(sl, 4)
                            signal_data['rr'] = 1.5  # Risk/Reward
                            
                            # Adicionar sinal
                            signal = signal_manager.add_signal(signal_data)
                            
                            if signal:
                                signals_found += 1
                                logger.info(f"Sinal encontrado: {symbol} {signal_data['direction']} "
                                          f"a ${price:.4f} (Conf: {signal_data['confidence']}%)")
                            
                            # Não gerar múltiplos sinais seguidos
                            time.sleep(2)
                    
                    except Exception as e:
                        logger.error(f"Erro analisando {symbol}: {e}")
                        continue
            
            if signals_found == 0:
                logger.info("Nenhum sinal forte encontrado nesta análise")
            
            # Esperar antes da próxima análise
            wait_time = 300  # 5 minutos
            logger.info(f"Próxima análise em {wait_time//60} minutos")
            time.sleep(wait_time)
        
        except Exception as e:
            logger.error(f"Erro na análise do mercado: {e}")
            time.sleep(60)

# =========================
# ROTAS WEB
# =========================

@app.route('/')
def dashboard():
    """Dashboard principal"""
    recent_signals = signal_manager.get_recent_signals(20)
    
    html = '''
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Crypto Signals - Análise Técnica</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body {
                background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
                color: #e2e8f0;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                min-height: 100vh;
            }
            .card-custom {
                background: rgba(30, 41, 59, 0.8);
                border: 1px solid #334155;
                border-radius: 12px;
                transition: all 0.3s ease;
            }
            .card-custom:hover {
                border-color: #3b82f6;
                transform: translateY(-2px);
            }
            .signal-buy {
                border-left: 4px solid #10b981;
            }
            .signal-sell {
                border-left: 4px solid #ef4444;
            }
            .badge-confidence {
                font-size: 0.8rem;
                padding: 4px 12px;
                border-radius: 20px;
            }
            .navbar-custom {
                background: #1e293b;
                border-bottom: 2px solid #3b82f6;
            }
        </style>
    </head>
    <body>
        <nav class="navbar navbar-expand-lg navbar-dark navbar-custom">
            <div class="container">
                <a class="navbar-brand fw-bold" href="#">
                    <span style="color: #3b82f6;">CRYPTO</span> 
                    <span style="color: #10b981;">SIGNALS</span>
                </a>
                <div class="d-flex">
                    <span class="badge bg-success">
                        <i class="fas fa-circle me-1"></i> ATIVO
                    </span>
                </div>
            </div>
        </nav>
        
        <div class="container mt-4">
            <div class="row mb-4">
                <div class="col-md-3">
                    <div class="card-custom p-3 text-center">
                        <div class="text-muted small">TOTAL DE SINAIS</div>
                        <div class="h2 fw-bold">{{ stats.total_signals }}</div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card-custom p-3 text-center">
                        <div class="text-muted small">COMPRAS</div>
                        <div class="h2 fw-bold text-success">{{ stats.buy_signals }}</div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card-custom p-3 text-center">
                        <div class="text-muted small">VENDAS</div>
                        <div class="h2 fw-bold text-danger">{{ stats.sell_signals }}</div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card-custom p-3 text-center">
                        <div class="text-muted small">ÚLTIMA ATUALIZAÇÃO</div>
                        <div class="h5 fw-bold">{{ last_update }}</div>
                    </div>
                </div>
            </div>
            
            <h3 class="mb-3">
                <i class="fas fa-bolt text-warning me-2"></i>
                Sinais Recentes
            </h3>
            
            {% if signals %}
                {% for signal in signals|reverse %}
                <div class="card-custom p-3 mb-3 {{ 'signal-buy' if signal.data.direction == 'COMPRA' else 'signal-sell' }}">
                    <div class="row align-items-center">
                        <div class="col-md-8">
                            <div class="d-flex align-items-center mb-2">
                                <h5 class="fw-bold mb-0 me-3">{{ signal.data.symbol }}</h5>
                                <span class="badge {{ 'bg-success' if signal.data.direction == 'COMPRA' else 'bg-danger' }} me-2">
                                    {{ signal.data.direction }}
                                </span>
                                <span class="badge bg-dark me-2">{{ signal.data.timeframe }}</span>
                                <span class="badge-confidence bg-primary">
                                    {{ signal.data.confidence }}% Confiança
                                </span>
                            </div>
                            
                            <div class="row mb-2">
                                <div class="col-4">
                                    <small class="text-muted">ENTRADA</small>
                                    <div class="h5 fw-bold">${{ "%.4f"|format(signal.data.price) }}</div>
                                </div>
                                <div class="col-4">
                                    <small class="text-muted">TAKE PROFIT</small>
                                    <div class="h5 fw-bold text-success">${{ signal.data.tp }}</div>
                                </div>
                                <div class="col-4">
                                    <small class="text-muted">STOP LOSS</small>
                                    <div class="h5 fw-bold text-danger">${{ signal.data.sl }}</div>
                                </div>
                            </div>
                            
                            <div class="mb-2">
                                <small class="text-muted">INDICADORES:</small>
                                <div>
                                    <span class="badge bg-secondary me-1">
                                        RSI: {{ signal.data.indicators.rsi }}
                                    </span>
                                    <span class="badge bg-secondary me-1">
                                        SMA20: {{ "%.4f"|format(signal.data.indicators.sma20) }}
                                    </span>
                                    <span class="badge bg-secondary">
                                        SMA50: {{ "%.4f"|format(signal.data.indicators.sma50) }}
                                    </span>
                                </div>
                            </div>
                            
                            <div class="text-muted small">
                                <i class="fas fa-clock me-1"></i> {{ signal.time }} • 
                                <i class="fas fa-calendar me-1"></i> {{ signal.date }}
                            </div>
                        </div>
                        
                        <div class="col-md-4">
                            <div class="card-custom bg-dark p-3">
                                <small class="text-muted">MOTIVOS DO SINAL</small>
                                <ul class="mt-2 mb-0" style="padding-left: 20px;">
                                    {% for reason in signal.data.reasons %}
                                    <li class="small">{{ reason }}</li>
                                    {% endfor %}
                                </ul>
                                <hr class="my-2">
                                <div class="small text-muted">
                                    <i class="fas fa-brain me-1"></i>
                                    Sentimento: {{ signal.data.sentiment }}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                {% endfor %}
            {% else %}
                <div class="card-custom p-5 text-center">
                    <i class="fas fa-chart-line fa-3x text-primary mb-3"></i>
                    <h4 class="text-muted">Analisando mercado...</h4>
                    <p class="text-muted">Os primeiros sinais aparecerão em breve</p>
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">Carregando...</span>
                    </div>
                </div>
            {% endif %}
            
            <div class="text-center mt-4 text-muted small">
                <p>
                    <i class="fas fa-exclamation-triangle me-1"></i>
                    Este sistema utiliza análise técnica para identificar oportunidades.
                    Sempre faça sua própria pesquisa antes de investir.
                </p>
                <p>Atualiza automaticamente a cada 30 segundos</p>
            </div>
        </div>
        
        <script>
            // Atualizar página automaticamente
            setTimeout(function() {
                location.reload();
            }, 30000); // 30 segundos
            
            // Adicionar ícones FontAwesome
            const faScript = document.createElement('script');
            faScript.src = 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/js/all.min.js';
            document.head.appendChild(faScript);
        </script>
    </body>
    </html>
    '''
    
    # Última atualização
    last_update = datetime.now().strftime("%H:%M:%S")
    
    return render_template_string(
        html,
        signals=recent_signals,
        stats=signal_manager.stats,
        last_update=last_update
    )

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'signals_count': len(signal_manager.signals),
        'uptime': time.time() - start_time
    })

@app.route('/api/signals')
def api_signals():
    """API para obter sinais"""
    signals = signal_manager.get_recent_signals(20)
    return jsonify({
        'count': len(signals),
        'signals': signals,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/analyze/<symbol>')
def analyze_symbol(symbol):
    """API para analisar um símbolo específico"""
    signal = analisar_cripto(symbol.upper())
    
    if signal:
        return jsonify({
            'success': True,
            'signal': signal
        })
    else:
        return jsonify({
            'success': False,
            'message': 'Nenhum sinal encontrado'
        })

# =========================
# INICIALIZAÇÃO
# =========================

if __name__ == '__main__':
    print("=" * 60)
    print("CRYPTO SIGNALS - ANÁLISE TÉCNICA")
    print("=" * 60)
    print(f"Analisando: {', '.join(CRYPTO_PAIRS)}")
    print(f"Dashboard: http://localhost:{PORT}")
    print(f"Health check: http://localhost:{PORT}/health")
    print("=" * 60)
    
    # Iniciar thread de análise
    analysis_thread = threading.Thread(target=analyze_market, daemon=True)
    analysis_thread.start()
    
    # Iniciar servidor web
    app.run(
        host='0.0.0.0',
        port=PORT,
        debug=False,
        threaded=True
    )
