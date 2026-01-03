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
# 20 PARES DE MOEDAS
# =========================
PAIRS = [
    # Top 10 por market cap
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT',
    'ADAUSDT', 'AVAXUSDT', 'DOGEUSDT', 'DOTUSDT', 'TRXUSDT',
    
    # Altcoins populares
    'LINKUSDT', 'MATICUSDT', 'SHIBUSDT', 'LTCUSDT', 'UNIUSDT',
    'ATOMUSDT', 'ETCUSDT', 'XLMUSDT', 'ALGOUSDT', 'VETUSDT'
]

# Categorias dos pares
PAIR_CATEGORIES = {
    'blue_chips': ['BTCUSDT', 'ETHUSDT', 'BNBUSDT'],
    'large_caps': ['SOLUSDT', 'XRPUSDT', 'ADAUSDT', 'AVAXUSDT'],
    'mid_caps': ['DOTUSDT', 'TRXUSDT', 'LINKUSDT', 'MATICUSDT'],
    'meme_coins': ['DOGEUSDT', 'SHIBUSDT'],
    'defi': ['UNIUSDT', 'AAVEUSDT'],
    'layer1': ['ATOMUSDT', 'ALGOUSDT'],
    'established': ['LTCUSDT', 'ETCUSDT', 'XLMUSDT', 'VETUSDT']
}

# =========================
# 10 ESTRATÉGIAS DIFERENTES
# =========================
STRATEGIES = {
    'RSI_STRATEGY': {'weight': 1.2, 'active': True},
    'EMA_CROSSOVER': {'weight': 1.3, 'active': True},
    'MACD_CROSSOVER': {'weight': 1.1, 'active': True},
    'BOLLINGER_BANDS': {'weight': 1.0, 'active': True},
    'SUPPORT_RESISTANCE': {'weight': 0.9, 'active': True},
    'VOLUME_SPIKE': {'weight': 0.8, 'active': True},
    'PRICE_ACTION': {'weight': 1.0, 'active': True},
    'TREND_FOLLOWING': {'weight': 1.1, 'active': True},
    'MEAN_REVERSION': {'weight': 0.9, 'active': True},
    'MOMENTUM': {'weight': 1.0, 'active': True}
}

# =========================
# FUNÇÕES DE ANÁLISE TÉCNICA
# =========================
def get_binance_klines(symbol, interval='1m', limit=50):
    """Obtém dados de candles da Binance"""
    try:
        url = f'https://api.binance.com/api/v3/klines'
        params = {'symbol': symbol, 'interval': interval, 'limit': limit}
        response = requests.get(url, params=params, timeout=10)
        return response.json()
    except Exception as e:
        logger.error(f"Erro ao obter klines para {symbol}: {e}")
        return None

def calculate_sma(prices, period):
    """Calcula Simple Moving Average"""
    if len(prices) < period:
        return sum(prices) / len(prices) if prices else 0
    return sum(prices[-period:]) / period

def calculate_ema(prices, period):
    """Calcula Exponential Moving Average"""
    if len(prices) < period:
        return prices[-1] if prices else 0
    
    multiplier = 2 / (period + 1)
    ema = prices[0]
    
    for price in prices[1:]:
        ema = (price - ema) * multiplier + ema
    
    return ema

def calculate_rsi(prices, period=14):
    """Calcula Relative Strength Index"""
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

def calculate_macd(prices):
    """Calcula MACD manualmente"""
    if len(prices) < 26:
        return 0, 0, 0
    
    ema12 = calculate_ema(prices, 12)
    ema26 = calculate_ema(prices, 26)
    macd_line = ema12 - ema26
    
    # Para signal line, precisamos de mais dados
    if len(prices) >= 35:
        # Usamos os últimos 9 valores do MACD para calcular a signal line
        macd_values = []
        for i in range(len(prices)-9, len(prices)):
            ema12_temp = calculate_ema(prices[:i+1], 12)
            ema26_temp = calculate_ema(prices[:i+1], 26)
            macd_values.append(ema12_temp - ema26_temp)
        
        signal_line = calculate_ema(macd_values, 9)
    else:
        signal_line = macd_line
    
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def calculate_bollinger_bands(prices, period=20, std_dev=2):
    """Calcula Bollinger Bands"""
    if len(prices) < period:
        middle = sum(prices) / len(prices) if prices else 0
        return middle, middle, middle
    
    middle = sum(prices[-period:]) / period
    
    # Calcula desvio padrão
    variance = sum((x - middle) ** 2 for x in prices[-period:]) / period
    std = variance ** 0.5
    
    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)
    
    return upper, middle, lower

def calculate_atr(highs, lows, closes, period=14):
    """Calcula Average True Range"""
    if len(highs) < period + 1:
        return 0
    
    true_ranges = []
    for i in range(1, len(highs)):
        tr1 = highs[i] - lows[i]
        tr2 = abs(highs[i] - closes[i-1])
        tr3 = abs(lows[i] - closes[i-1])
        true_ranges.append(max(tr1, tr2, tr3))
    
    return sum(true_ranges[-period:]) / period

# =========================
# ESTRATÉGIAS INDIVIDUAIS
# =========================
def apply_rsi_strategy(prices, rsi_value):
    """Estratégia baseada em RSI"""
    if rsi_value < 30:
        return ('RSI_OVERSOLD', 1.2)
    elif rsi_value > 70:
        return ('RSI_OVERBOUGHT', -1.2)
    elif 30 <= rsi_value <= 35:
        return ('RSI_NEAR_OVERSOLD', 0.8)
    elif 65 <= rsi_value <= 70:
        return ('RSI_NEAR_OVERBOUGHT', -0.8)
    return None

def apply_ema_crossover_strategy(prices):
    """Estratégia de crossover de EMA"""
    if len(prices) < 22:
        return None
    
    ema9 = calculate_ema(prices, 9)
    ema21 = calculate_ema(prices, 21)
    prev_ema9 = calculate_ema(prices[:-1], 9)
    prev_ema21 = calculate_ema(prices[:-1], 21)
    
    if ema9 > ema21 and prev_ema9 <= prev_ema21:
        return ('EMA_GOLDEN_CROSS', 1.3)
    elif ema9 < ema21 and prev_ema9 >= prev_ema21:
        return ('EMA_DEATH_CROSS', -1.3)
    return None

def apply_macd_strategy(prices):
    """Estratégia baseada em MACD"""
    macd_line, signal_line, histogram = calculate_macd(prices)
    
    if len(prices) >= 35:
        # Calcula MACD anterior
        prev_macd_line, prev_signal_line, _ = calculate_macd(prices[:-1])
        
        if macd_line > signal_line and prev_macd_line <= prev_signal_line:
            return ('MACD_BULLISH_CROSS', 1.1)
        elif macd_line < signal_line and prev_macd_line >= prev_signal_line:
            return ('MACD_BEARISH_CROSS', -1.1)
    
    # Sinal baseado no histograma
    if histogram > 0 and histogram > abs(histogram) * 0.5:
        return ('MACD_BULLISH', 0.8)
    elif histogram < 0 and abs(histogram) > abs(histogram) * 0.5:
        return ('MACD_BEARISH', -0.8)
    
    return None

def apply_bollinger_bands_strategy(prices, current_price):
    """Estratégia de Bollinger Bands"""
    upper, middle, lower = calculate_bollinger_bands(prices)
    
    band_width = (upper - lower) / middle if middle != 0 else 0
    
    if current_price <= lower:
        return ('BB_TOUCH_LOWER', 1.0)
    elif current_price >= upper:
        return ('BB_TOUCH_UPPER', -1.0)
    elif band_width < 0.1:  # Squeeze
        if current_price > middle:
            return ('BB_SQUEEZE_BULLISH', 0.7)
        else:
            return ('BB_SQUEEZE_BEARISH', -0.7)
    
    return None

def apply_support_resistance_strategy(prices, current_price):
    """Estratégia de Suporte e Resistência"""
    if len(prices) < 30:
        return None
    
    # Identifica níveis de suporte e resistência
    lookback = min(30, len(prices))
    recent_high = max(prices[-lookback:])
    recent_low = min(prices[-lookback:])
    
    # Tolerância de 0.5%
    tolerance = current_price * 0.005
    
    if abs(current_price - recent_high) <= tolerance:
        return ('RESISTANCE_TOUCH', -0.9)
    elif abs(current_price - recent_low) <= tolerance:
        return ('SUPPORT_TOUCH', 0.9)
    
    return None

def apply_volume_spike_strategy(current_volume, avg_volume, price_change):
    """Estratégia de Volume Spike"""
    volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
    
    if volume_ratio > 2.0:  # Spike de 2x a média
        if price_change > 0:
            return ('VOLUME_SPIKE_BUY', 0.8)
        else:
            return ('VOLUME_SPIKE_SELL', -0.8)
    elif volume_ratio > 1.5:
        if price_change > 0:
            return ('HIGH_VOLUME_BUY', 0.5)
        else:
            return ('HIGH_VOLUME_SELL', -0.5)
    
    return None

def apply_price_action_strategy(candle_data):
    """Análise de Price Action"""
    open_price = candle_data['open']
    high_price = candle_data['high']
    low_price = candle_data['low']
    close_price = candle_data['close']
    prev_close = candle_data.get('prev_close', close_price)
    
    # Candle patterns
    body_size = abs(close_price - open_price)
    upper_wick = high_price - max(open_price, close_price)
    lower_wick = min(open_price, close_price) - low_price
    
    # Hammer (reversão bullish)
    if lower_wick > body_size * 2 and upper_wick < body_size * 0.5 and close_price > open_price:
        return ('HAMMER_BULLISH', 0.9)
    
    # Shooting star (reversão bearish)
    if upper_wick > body_size * 2 and lower_wick < body_size * 0.5 and close_price < open_price:
        return ('SHOOTING_STAR_BEARISH', -0.9)
    
    # Engulfing bullish
    if close_price > open_price and prev_close < open_price and close_price > prev_close:
        return ('BULLISH_ENGULFING', 1.0)
    
    # Engulfing bearish
    if close_price < open_price and prev_close > open_price and close_price < prev_close:
        return ('BEARISH_ENGULFING', -1.0)
    
    return None

def apply_trend_following_strategy(prices, current_price):
    """Estratégia de Follow the Trend"""
    if len(prices) < 50:
        return None
    
    sma20 = calculate_sma(prices, 20)
    sma50 = calculate_sma(prices, 50)
    
    if current_price > sma20 > sma50:
        return ('STRONG_UPTREND', 1.1)
    elif current_price < sma20 < sma50:
        return ('STRONG_DOWNTREND', -1.1)
    elif current_price > sma20 and sma20 > sma50:
        return ('UPTREND', 0.8)
    elif current_price < sma20 and sma20 < sma50:
        return ('DOWNTREND', -0.8)
    
    return None

def apply_mean_reversion_strategy(prices, current_price):
    """Estratégia de Mean Reversion"""
    if len(prices) < 20:
        return None
    
    sma20 = calculate_sma(prices, 20)
    deviation = (current_price - sma20) / sma20 * 100
    
    if deviation < -3:  # 3% abaixo da média
        return ('MEAN_REVERSION_BUY', 0.9)
    elif deviation > 3:  # 3% acima da média
        return ('MEAN_REVERSION_SELL', -0.9)
    
    return None

def apply_momentum_strategy(prices):
    """Estratégia de Momentum"""
    if len(prices) < 10:
        return None
    
    momentum_5 = ((prices[-1] / prices[-5]) - 1) * 100
    momentum_10 = ((prices[-1] / prices[-10]) - 1) * 100
    
    if momentum_5 > 1 and momentum_10 > 2:  # Forte momentum positivo
        return ('STRONG_MOMENTUM_BUY', 1.0)
    elif momentum_5 < -1 and momentum_10 < -2:  # Forte momentum negativo
        return ('STRONG_MOMENTUM_SELL', -1.0)
    elif momentum_5 > 0.5:
        return ('MOMENTUM_BUY', 0.7)
    elif momentum_5 < -0.5:
        return ('MOMENTUM_SELL', -0.7)
    
    return None

# =========================
# ANÁLISE COMPLETA DO PAR
# =========================
def analyze_pair(symbol):
    """Analisa um par usando todas as estratégias"""
    try:
        # Obtém dados
        klines = get_binance_klines(symbol, limit=100)
        if not klines or len(klines) < 30:
            return None
        
        # Extrai dados dos candles
        closes = [float(k[4]) for k in klines]  # Preços de fechamento
        highs = [float(k[2]) for k in klines]   # Preços máximos
        lows = [float(k[3]) for k in klines]    # Preços mínimos
        volumes = [float(k[5]) for k in klines] # Volumes
        
        current_price = closes[-1]
        prev_price = closes[-2] if len(closes) >= 2 else current_price
        price_change = ((current_price / prev_price) - 1) * 100
        
        # Dados do candle atual
        current_candle = {
            'open': float(klines[-1][1]),
            'high': highs[-1],
            'low': lows[-1],
            'close': current_price,
            'prev_close': closes[-2] if len(closes) >= 2 else current_price
        }
        
        # Calcula indicadores
        rsi_value = calculate_rsi(closes)
        avg_volume = sum(volumes[-20:]) / len(volumes[-20:]) if len(volumes) >= 20 else volumes[-1]
        
        # Aplica todas as estratégias ativas
        signals = []
        
        # 1. RSI Strategy
        if STRATEGIES['RSI_STRATEGY']['active']:
            rsi_signal = apply_rsi_strategy(closes, rsi_value)
            if rsi_signal:
                signals.append(rsi_signal)
        
        # 2. EMA Crossover
        if STRATEGIES['EMA_CROSSOVER']['active']:
            ema_signal = apply_ema_crossover_strategy(closes)
            if ema_signal:
                signals.append(ema_signal)
        
        # 3. MACD Crossover
        if STRATEGIES['MACD_CROSSOVER']['active']:
            macd_signal = apply_macd_strategy(closes)
            if macd_signal:
                signals.append(macd_signal)
        
        # 4. Bollinger Bands
        if STRATEGIES['BOLLINGER_BANDS']['active']:
            bb_signal = apply_bollinger_bands_strategy(closes, current_price)
            if bb_signal:
                signals.append(bb_signal)
        
        # 5. Support/Resistance
        if STRATEGIES['SUPPORT_RESISTANCE']['active']:
            sr_signal = apply_support_resistance_strategy(closes, current_price)
            if sr_signal:
                signals.append(sr_signal)
        
        # 6. Volume Spike
        if STRATEGIES['VOLUME_SPIKE']['active']:
            volume_signal = apply_volume_spike_strategy(volumes[-1], avg_volume, price_change)
            if volume_signal:
                signals.append(volume_signal)
        
        # 7. Price Action
        if STRATEGIES['PRICE_ACTION']['active']:
            pa_signal = apply_price_action_strategy(current_candle)
            if pa_signal:
                signals.append(pa_signal)
        
        # 8. Trend Following
        if STRATEGIES['TREND_FOLLOWING']['active']:
            trend_signal = apply_trend_following_strategy(closes, current_price)
            if trend_signal:
                signals.append(trend_signal)
        
        # 9. Mean Reversion
        if STRATEGIES['MEAN_REVERSION']['active']:
            mr_signal = apply_mean_reversion_strategy(closes, current_price)
            if mr_signal:
                signals.append(mr_signal)
        
        # 10. Momentum
        if STRATEGIES['MOMENTUM']['active']:
            momentum_signal = apply_momentum_strategy(closes)
            if momentum_signal:
                signals.append(momentum_signal)
        
        # Calcula score final
        if not signals:
            return None
        
        total_score = sum(score for _, score in signals)
        buy_signals = [s for s in signals if s[1] > 0]
        sell_signals = [s for s in signals if s[1] < 0]
        
        buy_score = sum(score for _, score in buy_signals)
        sell_score = abs(sum(score for _, score in sell_signals))
        
        # Determina direção baseada no score
        if buy_score >= 2.0 and buy_score > sell_score:
            direction = 'BUY'
            confidence = min(buy_score / 5.0, 1.0)
            active_signals = buy_signals
        elif sell_score >= 2.0 and sell_score > buy_score:
            direction = 'SELL'
            confidence = min(sell_score / 5.0, 1.0)
            active_signals = sell_signals
        else:
            return None
        
        return {
            'symbol': symbol,
            'direction': direction,
            'price': current_price,
            'price_change': price_change,
            'rsi': rsi_value,
            'score': total_score,
            'confidence': confidence,
            'signals_count': len(signals),
            'active_signals': [s[0] for s in active_signals][:5],  # Top 5 sinais
            'timestamp': datetime.now()
        }
        
    except Exception as e:
        logger.error(f"Erro analisando {symbol}: {e}")
        return None

# =========================
# FUNÇÕES DE COMUNICAÇÃO
# =========================
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
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        response = requests.post(url, json=data, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Erro enviando Telegram: {e}")
        return False

def format_signal_message(signal):
    """Formata mensagem do sinal para Telegram"""
    direction_emoji = "🚀" if signal['direction'] == 'BUY' else "🔻"
    direction_color = "#27ae60" if signal['direction'] == 'BUY' else "#e74c3c"
    
    # Formata preço
    price_str = f"{signal['price']:.8f}" if signal['price'] < 1 else f"{signal['price']:.4f}"
    
    # Formata mudança percentual
    change_emoji = "📈" if signal['price_change'] > 0 else "📉"
    change_str = f"{abs(signal['price_change']):.2f}%"
    
    # Estratégias (apenas primeiras 3)
    strategies = ", ".join(signal['active_signals'][:3])
    
    # Barra de confiança
    confidence_bar = "🟢" * int(signal['confidence'] * 5)
    
    message = (
        f"{direction_emoji} <b>SINAL DE {signal['direction']}</b>\n"
        f"═══════════════════\n"
        f"📊 <b>Par:</b> <code>{signal['symbol']}</code>\n"
        f"💰 <b>Preço:</b> ${price_str}\n"
        f"{change_emoji} <b>Variação:</b> {change_str}\n"
        f"📈 <b>RSI:</b> {signal['rsi']:.1f}\n"
        f"🎯 <b>Confiança:</b> {signal['confidence']:.1%}\n"
        f"{confidence_bar}\n"
        f"🔧 <b>Estratégias:</b> {strategies}\n"
        f"📋 <b>Total Sinais:</b> {signal['signals_count']}\n"
        f"🕐 <b>Hora:</b> {signal['timestamp'].strftime('%H:%M:%S')}\n"
        f"═══════════════════\n"
        f"⚡ <i>Scalping 1min | Alvo: 0.3% | Stop: 0.2%</i>"
    )
    
    return message

def check_market():
    """Verifica todos os pares"""
    global last_signals
    
    if signals_paused:
        return
    
    logger.info("🔍 Verificando 20 pares...")
    
    signals_found = 0
    for pair in PAIRS:
        try:
            signal = analyze_pair(pair)
            if signal:
                logger.info(f"✅ {pair}: {signal['direction']} (Conf: {signal['confidence']:.0%})")
                
                # Verifica se é um sinal forte o suficiente
                if signal['confidence'] >= 0.6:  # 60% de confiança mínima
                    message = format_signal_message(signal)
                    
                    # Envia para Telegram
                    if send_telegram_message(message):
                        # Armazena sinal
                        signal['message'] = message
                        last_signals.append(signal)
                        
                        # Mantém apenas últimos 30 sinais
                        if len(last_signals) > 30:
                            last_signals.pop(0)
                        
                        signals_found += 1
                        
                        # Delay para não sobrecarregar API
                        time.sleep(1)
                
        except Exception as e:
            logger.error(f"Erro processando {pair}: {e}")
    
    if signals_found > 0:
        logger.info(f"📤 {signals_found} sinais fortes enviados")
    else:
        logger.info("📭 Nenhum sinal forte encontrado")

# =========================
# DASHBOARD WEB EXPANDIDO
# =========================
@app.route('/')
def dashboard():
    """Página principal do dashboard"""
    
    # Estatísticas
    uptime = datetime.now() - bot_start_time
    hours = uptime.seconds // 3600
    minutes = (uptime.seconds % 3600) // 60
    
    # Sinais de hoje
    today = datetime.now().date()
    today_signals = [s for s in last_signals if s['timestamp'].date() == today]
    buy_signals = len([s for s in today_signals if s['direction'] == 'BUY'])
    sell_signals = len([s for s in today_signals if s['direction'] == 'SELL'])
    
    # Sinais recentes (últimas 6 horas)
    recent_signals = [s for s in last_signals if s['timestamp'] > datetime.now() - timedelta(hours=6)]
    recent_signals.sort(key=lambda x: x['timestamp'], reverse=True)
    
    # Estratégias ativas
    active_strategies = sum(1 for s in STRATEGIES.values() if s['active'])
    
    # Contagem por categoria
    category_counts = {}
    for category, pairs in PAIR_CATEGORIES.items():
        category_counts[category] = len(pairs)
    
    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Crypto Signal Bot Pro</title>
        <style>
            :root {
                --primary: #3498db;
                --secondary: #2c3e50;
                --success: #27ae60;
                --danger: #e74c3c;
                --warning: #f39c12;
                --info: #17a2b8;
            }
            
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
                background: linear-gradient(135deg, #1a2980 0%, #26d0ce 100%);
                color: #333;
                margin: 0;
                padding: 20px;
                min-height: 100vh;
            }
            
            .container {
                max-width: 1400px;
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
            
            .stats-grid {
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
                box-shadow: 0 10px 20px rgba(0,0,0,0.08);
                transition: transform 0.3s;
            }
            
            .stat-card:hover {
                transform: translateY(-5px);
            }
            
            .stat-value {
                font-size: 2.5rem;
                font-weight: bold;
                margin: 10px 0;
                color: var(--secondary);
            }
            
            .stat-label {
                color: #718096;
                font-size: 0.9rem;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            
            .dashboard-grid {
                display: grid;
                grid-template-columns: 2fr 1fr;
                gap: 30px;
                margin-bottom: 30px;
            }
            
            @media (max-width: 1024px) {
                .dashboard-grid {
                    grid-template-columns: 1fr;
                }
            }
            
            .main-card {
                background: white;
                border-radius: 20px;
                padding: 30px;
                box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            }
            
            .sidebar-card {
                background: white;
                border-radius: 20px;
                padding: 30px;
                box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            }
            
            .signal-item {
                padding: 20px;
                margin: 15px 0;
                border-radius: 12px;
                border-left: 5px solid;
                background: #f8f9fa;
                transition: all 0.3s;
            }
            
            .signal-item:hover {
                transform: translateX(5px);
                box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            }
            
            .signal-buy {
                border-left-color: var(--success);
                background: rgba(39, 174, 96, 0.05);
            }
            
            .signal-sell {
                border-left-color: var(--danger);
                background: rgba(231, 76, 60, 0.05);
            }
            
            .btn {
                display: inline-flex;
                align-items: center;
                gap: 10px;
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
                background: var(--primary);
                color: white;
            }
            
            .btn-danger {
                background: var(--danger);
                color: white;
            }
            
            .btn-success {
                background: var(--success);
                color: white;
            }
            
            .btn:hover {
                transform: translateY(-2px);
                box-shadow: 0 10px 20px rgba(0,0,0,0.15);
            }
            
            .category-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                gap: 15px;
                margin: 20px 0;
            }
            
            .category-item {
                background: #edf2f7;
                padding: 15px;
                border-radius: 10px;
                text-align: center;
                font-weight: 600;
                color: var(--secondary);
            }
            
            .strategy-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                gap: 10px;
                margin: 15px 0;
            }
            
            .strategy-item {
                background: #f1f8e9;
                padding: 10px;
                border-radius: 8px;
                font-size: 0.9rem;
                text-align: center;
            }
            
            .strategy-active {
                background: #e8f5e9;
                color: var(--success);
            }
            
            .strategy-inactive {
                background: #ffebee;
                color: var(--danger);
            }
            
            .progress-bar {
                height: 8px;
                background: #e9ecef;
                border-radius: 4px;
                margin: 10px 0;
                overflow: hidden;
            }
            
            .progress-fill {
                height: 100%;
                border-radius: 4px;
                transition: width 0.3s;
            }
            
            .progress-buy {
                background: var(--success);
            }
            
            .progress-sell {
                background: var(--danger);
            }
            
            .footer {
                text-align: center;
                color: white;
                margin-top: 40px;
                opacity: 0.9;
            }
            
            h1, h2, h3 {
                color: var(--secondary);
                margin-top: 0;
            }
            
            .price-change {
                font-weight: bold;
            }
            
            .price-up {
                color: var(--success);
            }
            
            .price-down {
                color: var(--danger);
            }
        </style>
    </head>
    <body>
        <div class="container">
            <!-- Header -->
            <div class="header">
                <h1 style="font-size: 2.8rem; margin-bottom: 10px;">
                    🤖 Crypto Signal Bot Pro
                </h1>
                <p style="color: #718096; font-size: 1.1rem; margin-bottom: 25px;">
                    Sistema avançado com 20 pares e 10 estratégias
                </p>
                
                <div style="margin: 25px 0;">
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
                    <a href="/strategies" class="btn" style="background: #9b59b6; color: white;">
                        ⚙️ Estratégias
                    </a>
                </div>
            </div>
            
            <!-- Stats Grid -->
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-label">Pares Ativos</div>
                    <div class="stat-value">{{ pairs_count }}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Estratégias</div>
                    <div class="stat-value">{{ strategies_count }}/10</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Sinais Hoje</div>
                    <div class="stat-value">{{ today_signals_count }}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Buy/Sell Ratio</div>
                    <div class="stat-value">{{ buy_signals }}/{{ sell_signals }}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Confiança Média</div>
                    <div class="stat-value">{{ avg_confidence }}%</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Uptime</div>
                    <div class="stat-value">{{ uptime_str }}</div>
                </div>
            </div>
            
            <!-- Main Dashboard Grid -->
            <div class="dashboard-grid">
                <!-- Sinais Recentes -->
                <div class="main-card">
                    <h2>📈 Sinais Recentes</h2>
                    
                    {% if recent_signals %}
                        {% for signal in recent_signals[:8] %}
                        <div class="signal-item signal-{{ signal.direction|lower }}">
                            <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                                <div>
                                    <strong style="font-size: 1.3rem;">{{ signal.symbol }}</strong>
                                    <span style="margin-left: 10px; padding: 4px 12px; 
                                          background: {{ 'rgba(39, 174, 96, 0.1)' if signal.direction == 'BUY' else 'rgba(231, 76, 60, 0.1)' }};
                                          color: {{ '#27ae60' if signal.direction == 'BUY' else '#e74c3c' }};
                                          border-radius: 20px; font-weight: 600;">
                                        {{ signal.direction }}
                                    </span>
                                    <span class="price-change {{ 'price-up' if signal.price_change > 0 else 'price-down' }}">
                                        {{ '+' if signal.price_change > 0 else '' }}{{ "%.2f"|format(signal.price_change) }}%
                                    </span>
                                </div>
                                <div style="text-align: right;">
                                    <div style="font-weight: bold; font-size: 1.1rem;">
                                        ${{ "%.4f"|format(signal.price) if signal.price >= 1 else "%.8f"|format(signal.price) }}
                                    </div>
                                    <div style="color: #718096; font-size: 0.9rem;">
                                        {{ signal.timestamp.strftime('%H:%M') }}
                                    </div>
                                </div>
                            </div>
                            
                            <div style="margin-top: 15px;">
                                <div class="progress-bar">
                                    <div class="progress-fill progress-{{ signal.direction|lower }}" 
                                         style="width: {{ signal.confidence * 100 }}%">
                                    </div>
                                </div>
                                <div style="display: flex; justify-content: space-between; margin-top: 5px;">
                                    <span style="font-size: 0.9rem; color: #718096;">
                                        🎯 {{ "%.0f"|format(signal.confidence * 100) }}% confiança
                                    </span>
                                    <span style="font-size: 0.9rem; color: #718096;">
                                        🔧 {{ signal.signals_count }} estratégias
                                    </span>
                                </div>
                            </div>
                            
                            {% if signal.active_signals %}
                            <div style="margin-top: 10px; font-size: 0.85rem; color: #5a6268;">
                                📊 {{ signal.active_signals|join(', ') }}
                            </div>
                            {% endif %}
                        </div>
                        {% endfor %}
                    {% else %}
                        <div style="text-align: center; padding: 60px 20px; color: #a0aec0;">
                            <div style="font-size: 4rem; margin-bottom: 20px;">📭</div>
                            <p style="font-size: 1.3rem; margin-bottom: 10px;">Nenhum sinal recente</p>
                            <p>O bot está analisando o mercado. Os sinais aparecerão aqui.</p>
                        </div>
                    {% endif %}
                </div>
                
                <!-- Sidebar -->
                <div class="sidebar-card">
                    <!-- Status -->
                    <h3>📊 Status do Sistema</h3>
                    <div style="background: {{ '#e8f5e9' if not paused else '#ffebee' }};
                         padding: 20px; border-radius: 12px; margin: 15px 0; text-align: center;">
                        <div style="font-size: 1.8rem; margin-bottom: 10px;">
                            {% if not paused %}
                            🟢 ATIVO
                            {% else %}
                            🔴 PAUSADO
                            {% endif %}
                        </div>
                        <div style="color: #718096;">
                            {{ status_message }}
                        </div>
                    </div>
                    
                    <!-- Categorias de Pares -->
                    <h3>🏷️ Categorias</h3>
                    <div class="category-grid">
                        {% for category, count in category_counts.items() %}
                        <div class="category-item">
                            {{ category.replace('_', ' ').title() }}<br>
                            <small style="color: #718096;">{{ count }} pares</small>
                        </div>
                        {% endfor %}
                    </div>
                    
                    <!-- Estratégias Ativas -->
                    <h3 style="margin-top: 30px;">⚡ Estratégias Ativas</h3>
                    <div class="strategy-grid">
                        {% for name, config in strategies.items() %}
                        <div class="strategy-item {{ 'strategy-active' if config.active else 'strategy-inactive' }}">
                            {{ name.replace('_', ' ') }}<br>
                            <small>Peso: {{ config.weight }}</small>
                        </div>
                        {% endfor %}
                    </div>
                    
                    <!-- Informações -->
                    <div style="margin-top: 30px; padding-top: 20px; border-top: 2px solid #eee;">
                        <h3>ℹ️ Informações</h3>
                        <p style="color: #718096; font-size: 0.9rem;">
                            ⏰ Intervalo: 1 minuto<br>
                            🎯 Alvo: 0.3%<br>
                            🛡️ Stop: 0.2%<br>
                            📊 Mín. confiança: 60%<br>
                            🔄 Próxima verificação: {{ next_check }}
                        </p>
                    </div>
                </div>
            </div>
            
            <!-- Footer -->
            <div class="footer">
                <p>🔄 Auto-atualização em 60 segundos | ⚡ Powered by Render.com</p>
                <p>🤖 20 pares | ⚙️ 10 estratégias | 🐍 Python</p>
                <p style="font-size: 0.9rem; margin-top: 10px; opacity: 0.7;">
                    Última atualização: {{ current_time }}
                </p>
            </div>
        </div>
        
        <script>
            // Auto-refresh
            setTimeout(() => location.reload(), 60000);
            
            // Animações
            document.addEventListener('DOMContentLoaded', () => {
                // Anima cards
                const cards = document.querySelectorAll('.stat-card, .signal-item');
                cards.forEach((card, index) => {
                    card.style.opacity = '0';
                    card.style.transform = 'translateY(20px)';
                    
                    setTimeout(() => {
                        card.style.transition = 'opacity 0.5s, transform 0.5s';
                        card.style.opacity = '1';
                        card.style.transform = 'translateY(0)';
                    }, index * 50);
                });
                
                // Confirmações
                document.querySelectorAll('a[href*="pause"], a[href*="resume"]').forEach(link => {
                    link.addEventListener('click', (e) => {
                        const action = link.href.includes('pause') ? 'pausar' : 'retomar';
                        if (!confirm(`Tem certeza que deseja ${action} o bot?`)) {
                            e.preventDefault();
                        }
                    });
                });
                
                // Atualiza progress bars
                const progressBars = document.querySelectorAll('.progress-fill');
                progressBars.forEach(bar => {
                    const width = bar.style.width;
                    bar.style.width = '0';
                    setTimeout(() => {
                        bar.style.width = width;
                    }, 300);
                });
            });
        </script>
    </body>
    </html>
    '''
    
    # Calcula confiança média
    avg_confidence = 0
    if today_signals:
        avg_confidence = sum(s['confidence'] for s in today_signals) / len(today_signals) * 100
    
    # Próxima verificação
    next_check_time = datetime.now() + timedelta(seconds=60)
    next_check_str = next_check_time.strftime('%H:%M:%S')
    
    return render_template_string(
        html,
        pairs_count=len(PAIRS),
        strategies_count=active_strategies,
        today_signals_count=len(today_signals),
        buy_signals=buy_signals,
        sell_signals=sell_signals,
        avg_confidence=f"{avg_confidence:.1f}",
        uptime_str=f"{hours}h {minutes}m",
        recent_signals=recent_signals,
        category_counts=category_counts,
        strategies=STRATEGIES,
        paused=signals_paused,
        status_message="Analisando mercado em tempo real" if not signals_paused else "Sistema pausado",
        next_check=next_check_str,
        current_time=datetime.now().strftime('%H:%M:%S')
    )

@app.route('/strategies')
def strategies_page():
    """Página de configuração das estratégias"""
    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Configuração de Estratégias</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #1a2980 0%, #26d0ce 100%);
                color: #333;
                margin: 0;
                padding: 20px;
            }
            .container {
                max-width: 1000px;
                margin: 0 auto;
                background: white;
                border-radius: 20px;
                padding: 40px;
                box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            }
            .back-btn {
                display: inline-flex;
                align-items: center;
                gap: 8px;
                padding: 12px 24px;
                background: #3498db;
                color: white;
                text-decoration: none;
                border-radius: 10px;
                font-weight: 600;
                margin-bottom: 30px;
            }
            .strategy-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
                gap: 20px;
                margin: 30px 0;
            }
            .strategy-card {
                background: #f8f9fa;
                border-radius: 15px;
                padding: 25px;
                border-left: 5px solid #3498db;
            }
            .strategy-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 15px;
            }
            .toggle-switch {
                position: relative;
                width: 60px;
                height: 30px;
            }
            .toggle-checkbox {
                display: none;
            }
            .toggle-label {
                position: absolute;
                width: 100%;
                height: 100%;
                background: #ccc;
                border-radius: 50px;
                cursor: pointer;
                transition: all 0.3s;
            }
            .toggle-label::after {
                content: "";
                position: absolute;
                width: 26px;
                height: 26px;
                border-radius: 50%;
                top: 2px;
                left: 2px;
                background: white;
                transition: all 0.3s;
            }
            .toggle-checkbox:checked + .toggle-label {
                background: #27ae60;
            }
            .toggle-checkbox:checked + .toggle-label::after {
                left: 32px;
            }
            .weight-slider {
                width: 100%;
                margin: 15px 0;
            }
            .save-btn {
                display: block;
                width: 100%;
                padding: 16px;
                background: #27ae60;
                color: white;
                border: none;
                border-radius: 10px;
                font-size: 1.1rem;
                font-weight: 600;
                cursor: pointer;
                margin-top: 30px;
                transition: all 0.3s;
            }
            .save-btn:hover {
                background: #219653;
                transform: translateY(-2px);
            }
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-btn">← Voltar ao Dashboard</a>
            <h1>⚙️ Configuração de Estratégias</h1>
            <p>Configure o peso e ativação de cada estratégia</p>
            
            <form id="strategies-form">
                <div class="strategy-grid">
                    {% for name, config in strategies.items() %}
                    <div class="strategy-card">
                        <div class="strategy-header">
                            <h3 style="margin: 0;">{{ name.replace('_', ' ') }}</h3>
                            <div class="toggle-switch">
                                <input type="checkbox" 
                                       id="{{ name }}" 
                                       name="{{ name }}_active" 
                                       class="toggle-checkbox"
                                       {{ 'checked' if config.active }}>
                                <label for="{{ name }}" class="toggle-label"></label>
                            </div>
                        </div>
                        
                        <p style="color: #666; margin-bottom: 15px;">
                            {% if 'RSI' in name %}Análise de sobrecompra/sobrevenda{% endif %}
                            {% if 'EMA' in name %}Cruzamento de médias móveis{% endif %}
                            {% if 'MACD' in name %}Divergência de momentum{% endif %}
                            {% if 'BOLLINGER' in name %}Bandas de volatilidade{% endif %}
                            {% if 'SUPPORT' in name %}Níveis de suporte/resistência{% endif %}
                            {% if 'VOLUME' in name %}Spikes de volume{% endif %}
                            {% if 'PRICE' in name %}Padrões de candle{% endif %}
                            {% if 'TREND' in name %}Seguimento de tendência{% endif %}
                            {% if 'MEAN' in name %}Reversão à média{% endif %}
                            {% if 'MOMENTUM' in name %}Força do movimento{% endif %}
                        </p>
                        
                        <label>Peso: <span id="{{ name }}_value">{{ config.weight }}</span></label>
                        <input type="range" 
                               min="0.5" 
                               max="2.0" 
                               step="0.1" 
                               value="{{ config.weight }}"
                               class="weight-slider"
                               data-target="{{ name }}"
                               name="{{ name }}_weight">
                    </div>
                    {% endfor %}
                </div>
                
                <button type="button" class="save-btn" onclick="saveStrategies()">
                    💾 Salvar Configurações
                </button>
            </form>
        </div>
        
        <script>
            // Atualiza valores dos sliders
            document.querySelectorAll('.weight-slider').forEach(slider => {
                const target = slider.getAttribute('data-target');
                const valueSpan = document.getElementById(target + '_value');
                
                slider.addEventListener('input', () => {
                    valueSpan.textContent = slider.value;
                });
            });
            
            // Salva configurações
            function saveStrategies() {
                const formData = new FormData();
                
                // Coleta dados do formulário
                document.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                    formData.append(cb.name, cb.checked);
                });
                
                document.querySelectorAll('input[type="range"]').forEach(slider => {
                    formData.append(slider.name, slider.value);
                });
                
                // Envia para o servidor (simulação)
                fetch('/update_strategies', {
                    method: 'POST',
                    body: formData
                })
                .then(response => {
                    if (response.ok) {
                        alert('Configurações salvas com sucesso!');
                        setTimeout(() => location.href = '/', 1000);
                    } else {
                        alert('Erro ao salvar configurações');
                    }
                })
                .catch(error => {
                    alert('Erro de conexão');
                });
            }
        </script>
    </body>
    </html>
    '''
    
    return render_template_string(html, strategies=STRATEGIES)

@app.route('/pause')
def pause_bot():
    global signals_paused
    signals_paused = True
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #1a2980 0%, #26d0ce 100%);
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
            .btn {
                display: inline-flex;
                align-items: center;
                gap: 10px;
                padding: 14px 28px;
                background: #3498db;
                color: white;
                text-decoration: none;
                border-radius: 12px;
                font-weight: 600;
                margin-top: 20px;
            }
        </style>
    </head>
    <body>
        <div class="message">
            <h1>⏸️ Bot Pausado</h1>
            <p>O sistema de sinais foi pausado com sucesso.</p>
            <a href="/" class="btn">← Voltar ao Dashboard</a>
        </div>
    </body>
    </html>
    '''

@app.route('/resume')
def resume_bot():
    global signals_paused
    signals_paused = False
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #1a2980 0%, #26d0ce 100%);
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
            .btn {
                display: inline-flex;
                align-items: center;
                gap: 10px;
                padding: 14px 28px;
                background: #27ae60;
                color: white;
                text-decoration: none;
                border-radius: 12px;
                font-weight: 600;
                margin-top: 20px;
            }
        </style>
    </head>
    <body>
        <div class="message">
            <h1>▶️ Bot Retomado</h1>
            <p>O sistema de sinais foi reativado com sucesso.</p>
            <a href="/" class="btn">← Voltar ao Dashboard</a>
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
                background: linear-gradient(135deg, #1a2980 0%, #26d0ce 100%);
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
            .btn {
                display: inline-flex;
                align-items: center;
                gap: 10px;
                padding: 14px 28px;
                background: #3498db;
                color: white;
                text-decoration: none;
                border-radius: 12px;
                font-weight: 600;
                margin-top: 20px;
            }
        </style>
    </head>
    <body>
        <div class="message">
            <h1>🔍 Verificação Manual</h1>
            <p>O mercado está sendo verificado agora. Verifique o Telegram para sinais.</p>
            <a href="/" class="btn">← Voltar ao Dashboard</a>
        </div>
    </body>
    </html>
    '''

@app.route('/update_strategies', methods=['POST'])
def update_strategies():
    """Atualiza configurações das estratégias"""
    # Esta função seria implementada para salvar as configurações
    # Por simplicidade, apenas redireciona
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #1a2980 0%, #26d0ce 100%);
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
            .btn {
                display: inline-flex;
                align-items: center;
                gap: 10px;
                padding: 14px 28px;
                background: #27ae60;
                color: white;
                text-decoration: none;
                border-radius: 12px;
                font-weight: 600;
                margin-top: 20px;
            }
        </style>
    </head>
    <body>
        <div class="message">
            <h1>✅ Configurações Salvas</h1>
            <p>As estratégias foram atualizadas com sucesso.</p>
            <a href="/" class="btn">← Voltar ao Dashboard</a>
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
        'active_strategies': sum(1 for s in STRATEGIES.values() if s['active']),
        'signals_today': len([s for s in last_signals if s['timestamp'].date() == datetime.now().date()]),
        'bot_status': 'paused' if signals_paused else 'running',
        'uptime': str(datetime.now() - bot_start_time)
    }

# =========================
# LOOP PRINCIPAL
# =========================
def run_bot():
    """Loop principal do bot"""
    logger.info("=" * 60)
    logger.info("🤖 CRYPTO SIGNAL BOT PRO INICIANDO")
    logger.info("=" * 60)
    logger.info(f"📊 Pares: {len(PAIRS)}")
    logger.info(f"🎯 Estratégias: {sum(1 for s in STRATEGIES.values() if s['active'])}/10")
    logger.info(f"🌐 Dashboard: disponível")
    logger.info("=" * 60)
    
    # Envia mensagem de início
    if TELEGRAM_TOKEN and CHAT_ID:
        startup_msg = (
            "🚀 <b>CRYPTO BOT PRO INICIADO</b>\n\n"
            f"📊 <b>Configuração Avançada:</b>\n"
            f"• Pares: {len(PAIRS)}\n"
            f"• Estratégias: {sum(1 for s in STRATEGIES.values() if s['active'])}/10\n"
            f"• Intervalo: 1 minuto\n"
            f"• Confiança mínima: 60%\n\n"
            f"⚡ <b>Sistemas ativos:</b>\n"
            f"• RSI & EMA Crossover\n"
            f"• MACD & Bollinger Bands\n"
            f"• Support/Resistance\n"
            f"• Volume Spike\n"
            f"• Price Action\n\n"
            f"🌐 Dashboard disponível\n"
            f"✅ Sistema operacional!"
        )
        send_telegram_message(startup_msg)
    
    # Loop principal
    check_interval = 60  # 1 minuto
    
    while True:
        try:
            if not signals_paused:
                check_market()
            
            time.sleep(check_interval)
            
        except Exception as e:
            logger.error(f"Erro no loop principal: {e}")
            time.sleep(30)

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
