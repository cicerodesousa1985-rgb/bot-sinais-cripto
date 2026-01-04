import os
import time
import threading
import requests
import json
from datetime import datetime, timedelta
from flask import Flask, render_template_string, jsonify, request
import logging
import random

# =========================
# CONFIGURAÇÃO
# =========================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

signals_paused = False
last_signals = []
bot_start_time = datetime.now()

# =========================
# CONFIGURAÇÃO EXPANDIDA
# =========================
TIMEFRAMES = ['1m', '5m']  # 2 timeframes (mais rápido)

# 60+ PARES ORGANIZADOS POR VOLATILIDADE
PAIRS = [
    # HIGH VOLATILITY (20 pares - muitos sinais)
    'PEPEUSDT', 'FLOKIUSDT', 'BONKUSDT', 'WIFUSDT', 'SHIBUSDT',
    'MEMEUSDT', 'ORDIUSDT', 'JTOUSDT', 'JUPUSDT', 'PYTHUSDT',
    'DOGEUSDT', 'RUNEUSDT', 'GALAUSDT', 'CHZUSDT', 'ENJUSDT',
    'SANDUSDT', 'MANAUSDT', 'AXSUSDT', 'IMXUSDT', 'RNDRUSDT',
    
    # MEDIUM VOLATILITY (20 pares)
    'SOLUSDT', 'AVAXUSDT', 'MATICUSDT', 'ADAUSDT', 'DOTUSDT',
    'LINKUSDT', 'UNIUSDT', 'AAVEUSDT', 'ATOMUSDT', 'NEARUSDT',
    'FTMUSDT', 'ALGOUSDT', 'FILUSDT', 'ICPUSDT', 'VETUSDT',
    'ETCUSDT', 'XLMUSDT', 'APTUSDT', 'ARBUSDT', 'OPUSDT',
    
    # LOW VOLATILITY (20 pares)
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'XRPUSDT', 'LTCUSDT',
    'TRXUSDT', 'ADAUSDT', 'XRPUSDT', 'DOTUSDT', 'LINKUSDT',
    'MATICUSDT', 'UNIUSDT', 'ATOMUSDT', 'ETCUSDT', 'XLMUSDT',
    'ALGOUSDT', 'VETUSDT', 'FILUSDT', 'ICPUSDT', 'NEARUSDT'
]

# ESTRATÉGIAS SUPER AGRESSIVAS (vão gerar MUITOS sinais)
STRATEGIES = {
    # ESTRATÉGIAS DE ALTA FREQUÊNCIA
    'RSI_EXTREME_EXPANDED': {'weight': 1.8, 'active': True, 'type': 'momentum'},
    'STOCH_FAST_AGGRESSIVE': {'weight': 1.6, 'active': True, 'type': 'momentum'},
    'PRICE_BREAKOUT_EASY': {'weight': 1.7, 'active': True, 'type': 'breakout'},
    'VOLUME_SPIKE_3x': {'weight': 1.5, 'active': True, 'type': 'volume'},
    
    # ESTRATÉGIAS PARA MERCADO NEUTRO
    'MEAN_REVERSION_EASY': {'weight': 1.9, 'active': True, 'type': 'range'},
    'BB_TOUCH_SIMPLE': {'weight': 1.6, 'active': True, 'type': 'range'},
    'TREND_PULLBACK_QUICK': {'weight': 1.5, 'active': True, 'type': 'trend'},
    'PRICE_ACTION_SIMPLE': {'weight': 1.4, 'active': True, 'type': 'pattern'},
    
    # ESTRATÉGIAS DE MÉDIA FREQUÊNCIA
    'EMA_CROSS_QUICK': {'weight': 1.6, 'active': True, 'type': 'trend'},
    'SUPPORT_RESISTANCE_TOUCH': {'weight': 1.5, 'active': True, 'type': 'reversal'},
    'MOMENTUM_SHIFT': {'weight': 1.4, 'active': True, 'type': 'momentum'},
    'MARKET_STRUCTURE_BREAK': {'weight': 1.7, 'active': True, 'type': 'breakout'},
}

# =========================
# FUNÇÕES DE ANÁLISE
# =========================
def get_binance_klines(symbol, interval='1m', limit=50):
    """Obtém candles da Binance"""
    try:
        url = f"https://api.binance.com/api/v3/klines"
        params = {'symbol': symbol, 'interval': interval, 'limit': limit}
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.error(f"Erro klines {symbol}: {e}")
    return None

def calculate_indicators(prices, volumes=None):
    """Calcula indicadores técnicos"""
    if len(prices) < 10:
        return {}
    
    current_price = prices[-1]
    
    # SMA Simples
    sma10 = sum(prices[-10:]) / 10 if len(prices) >= 10 else current_price
    sma20 = sum(prices[-20:]) / 20 if len(prices) >= 20 else current_price
    
    # EMA Rápida
    ema9 = calculate_ema_simple(prices, 9)
    ema21 = calculate_ema_simple(prices, 21)
    
    # RSI Expandido
    rsi = calculate_rsi_expanded(prices)
    
    # Estocástico Agressivo
    stochastic = calculate_stochastic_aggressive(prices)
    
    # Suporte/Resistência Dinâmico
    recent_low = min(prices[-20:]) if len(prices) >= 20 else min(prices)
    recent_high = max(prices[-20:]) if len(prices) >= 20 else max(prices)
    
    return {
        'price': current_price,
        'sma10': sma10,
        'sma20': sma20,
        'ema9': ema9,
        'ema21': ema21,
        'rsi': rsi,
        'stochastic': stochastic,
        'recent_low': recent_low,
        'recent_high': recent_high,
        'prices': prices,
        'volumes': volumes[-20:] if volumes else None
    }

def calculate_ema_simple(prices, period):
    """EMA simplificada"""
    if len(prices) < period:
        return prices[-1] if prices else 0
    
    multiplier = 2 / (period + 1)
    ema = prices[0]
    
    for price in prices[1:]:
        ema = (price - ema) * multiplier + ema
    
    return ema

def calculate_rsi_expanded(prices, period=14):
    """RSI com zonas expandidas"""
    if len(prices) < period + 1:
        return 50
    
    gains = []
    losses = []
    
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100
    
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_stochastic_aggressive(prices, period=14):
    """Stochastic com zonas expandidas"""
    if len(prices) < period:
        return 50
    
    recent_low = min(prices[-period:])
    recent_high = max(prices[-period:])
    
    if recent_high == recent_low:
        return 50
    
    current = prices[-1]
    return ((current - recent_low) / (recent_high - recent_low)) * 100

# =========================
# ESTRATÉGIAS SUPER AGRESSIVAS
# =========================
def strategy_rsi_extreme_expanded(indicators):
    """RSI com zonas MUITO expandidas"""
    rsi = indicators['rsi']
    
    # ZONAS SUPER EXPANDIDAS
    if rsi < 40:  # Oversold expandido
        return ('COMPRA', 1.8, f'RSI BAIXO ({rsi:.1f})')
    elif rsi > 60:  # Overbought expandido
        return ('VENDA', 1.8, f'RSI ALTO ({rsi:.1f})')
    elif rsi < 45:
        return ('COMPRA', 1.2, f'RSI LEVE BAIXO ({rsi:.1f})')
    elif rsi > 55:
        return ('VENDA', 1.2, f'RSI LEVE ALTO ({rsi:.1f})')
    
    return None

def strategy_stoch_fast_aggressive(indicators):
    """Stochastic super agressivo"""
    stoch = indicators['stochastic']
    
    if stoch < 30:
        return ('COMPRA', 1.6, f'STOCH OVERSOLD ({stoch:.1f})')
    elif stoch > 70:
        return ('VENDA', 1.6, f'STOCH OVERBOUGHT ({stoch:.1f})')
    elif stoch < 40 and stoch > indicators.get('prev_stoch', 50):
        return ('COMPRA', 1.0, f'STOCH REVERSÃO ({stoch:.1f})')
    elif stoch > 60 and stoch < indicators.get('prev_stoch', 50):
        return ('VENDA', 1.0, f'STOCH REVERSÃO ({stoch:.1f})')
    
    return None

def strategy_price_breakout_easy(indicators):
    """Breakout fácil de detectar"""
    price = indicators['price']
    recent_high = indicators['recent_high']
    recent_low = indicators['recent_low']
    
    # Breakout MUITO sensível (0.1%)
    if price >= recent_high * 0.999:
        return ('COMPRA', 1.7, 'BREAKOUT RESISTÊNCIA')
    elif price <= recent_low * 1.001:
        return ('VENDA', 1.7, 'BREAKDOWN SUPORTE')
    
    # Toque em S/R (0.5%)
    if abs(price - recent_high) / recent_high < 0.005:
        return ('VENDA', 1.3, 'TOQUE RESISTÊNCIA')
    elif abs(price - recent_low) / recent_low < 0.005:
        return ('COMPRA', 1.3, 'TOQUE SUPORTE')
    
    return None

def strategy_volume_spike_3x(indicators):
    """Volume spike 3x"""
    if not indicators.get('volumes'):
        return None
    
    volumes = indicators['volumes']
    if len(volumes) < 10:
        return None
    
    current_volume = volumes[-1]
    avg_volume = sum(volumes[-10:]) / 10
    
    if current_volume > avg_volume * 2.5:  # 2.5x volume médio
        price = indicators['price']
        prev_price = indicators['prices'][-2] if len(indicators['prices']) >= 2 else price
        
        if price > prev_price:
            return ('COMPRA', 1.5, f'VOLUME PUMP ({(current_volume/avg_volume):.1f}x)')
        else:
            return ('VENDA', 1.5, f'VOLUME DUMP ({(current_volume/avg_volume):.1f}x)')
    
    return None

def strategy_mean_reversion_easy(indicators):
    """Mean Reversion FÁCIL"""
    price = indicators['price']
    sma10 = indicators['sma10']
    
    deviation = ((price - sma10) / sma10) * 100
    
    if abs(deviation) > 1.0:  # Apenas 1% de desvio!
        if deviation > 0:
            return ('VENDA', 1.9, f'+{abs(deviation):.1f}% acima da média')
        else:
            return ('COMPRA', 1.9, f'-{abs(deviation):.1f}% abaixo da média')
    
    return None

def strategy_bb_touch_simple(indicators):
    """Bollinger Bands simplificado"""
    if len(indicators.get('prices', [])) < 10:
        return None
    
    prices = indicators['prices'][-10:]
    current_price = indicators['price']
    
    # SMA 10
    sma10 = sum(prices) / len(prices)
    
    # Desvio padrão simplificado
    variance = sum((x - sma10) ** 2 for x in prices) / len(prices)
    std_dev = variance ** 0.5 if variance > 0 else 0
    
    # Bandas (1.5 std para mais sensibilidade)
    bb_upper = sma10 + (std_dev * 1.2)
    bb_lower = sma10 - (std_dev * 1.2)
    
    # Toque nas bandas
    if current_price >= bb_upper:
        return ('VENDA', 1.6, 'TOQUE BANDA SUPERIOR')
    elif current_price <= bb_lower:
        return ('COMPRA', 1.6, 'TOQUE BANDA INFERIOR')
    
    return None

def strategy_trend_pullback_quick(indicators):
    """Pullback rápido em tendência"""
    ema9 = indicators['ema9']
    ema21 = indicators['ema21']
    price = indicators['price']
    
    # Tendência de alta
    if ema9 > ema21:
        # Pullback para EMA9 (1% de tolerância)
        if price <= ema9 * 1.01:
            return ('COMPRA', 1.5, 'PULLBACK UPTREND')
    
    # Tendência de baixa
    elif ema9 < ema21:
        # Pullback para EMA9 (1% de tolerância)
        if price >= ema9 * 0.99:
            return ('VENDA', 1.5, 'PULLBACK DOWNTREND')
    
    return None

def strategy_price_action_simple(indicators):
    """Price action simplificado"""
    if len(indicators.get('prices', [])) < 3:
        return None
    
    prices = indicators['prices'][-3:]
    
    # Bullish simplificado
    if prices[-1] > prices[-2] > prices[-3]:
        return ('COMPRA', 1.4, '3 VERDES CONSECUTIVOS')
    
    # Bearish simplificado
    elif prices[-1] < prices[-2] < prices[-3]:
        return ('VENDA', 1.4, '3 VERMELHOS CONSECUTIVOS')
    
    # Doji/Reversão
    high = max(prices)
    low = min(prices)
    body = abs(prices[-1] - prices[-2])
    
    if body < (high - low) * 0.15:  # Corpo pequeno
        if prices[-1] > prices[-2]:
            return ('COMPRA', 1.2, 'DOJI BULLISH')
        else:
            return ('VENDA', 1.2, 'DOJI BEARISH')
    
    return None

def strategy_ema_cross_quick(indicators):
    """EMA crossover rápido"""
    ema9 = indicators['ema9']
    ema21 = indicators['ema21']
    
    # Diferença percentual
    diff_percent = abs((ema9 - ema21) / ema21 * 100)
    
    if diff_percent < 0.5:  # EMA's muito próximas
        if ema9 > ema21:
            return ('COMPRA', 1.6, 'EMA9 > EMA21 (PRÓXIMAS)')
        else:
            return ('VENDA', 1.6, 'EMA9 < EMA21 (PRÓXIMAS)')
    
    return None

def strategy_support_resistance_touch(indicators):
    """Toque em suporte/resistência"""
    price = indicators['price']
    recent_low = indicators['recent_low']
    recent_high = indicators['recent_high']
    
    # Toque em suporte (1%)
    if price <= recent_low * 1.01:
        return ('COMPRA', 1.5, 'TOQUE SUPORTE')
    
    # Toque em resistência (1%)
    elif price >= recent_high * 0.99:
        return ('VENDA', 1.5, 'TOQUE RESISTÊNCIA')
    
    return None

# =========================
# SISTEMA DE ANÁLISE
# =========================
def analyze_multi_timeframe(symbol):
    """Analisa em múltiplos timeframes"""
    signals = []
    
    for tf in TIMEFRAMES:
        try:
            klines = get_binance_klines(symbol, interval=tf, limit=30)
            if not klines or len(klines) < 15:
                continue
            
            closes = [float(k[4]) for k in klines]
            volumes = [float(k[5]) for k in klines]
            
            indicators = calculate_indicators(closes, volumes)
            
            # Aplica TODAS as estratégias
            tf_signals = apply_all_strategies(indicators)
            
            for sig in tf_signals:
                signals.append({
                    'timeframe': tf,
                    'signal': sig,
                    'weight': {'1m': 1.0, '5m': 1.3}[tf]
                })
                
        except Exception as e:
            logger.error(f"Erro {symbol} {tf}: {e}")
    
    return consolidate_signals(signals, symbol)

def apply_all_strategies(indicators):
    """Aplica TODAS as estratégias agressivas"""
    all_signals = []
    
    strategies_map = {
        'RSI_EXTREME_EXPANDED': strategy_rsi_extreme_expanded,
        'STOCH_FAST_AGGRESSIVE': strategy_stoch_fast_aggressive,
        'PRICE_BREAKOUT_EASY': strategy_price_breakout_easy,
        'VOLUME_SPIKE_3x': strategy_volume_spike_3x,
        'MEAN_REVERSION_EASY': strategy_mean_reversion_easy,
        'BB_TOUCH_SIMPLE': strategy_bb_touch_simple,
        'TREND_PULLBACK_QUICK': strategy_trend_pullback_quick,
        'PRICE_ACTION_SIMPLE': strategy_price_action_simple,
        'EMA_CROSS_QUICK': strategy_ema_cross_quick,
        'SUPPORT_RESISTANCE_TOUCH': strategy_support_resistance_touch,
    }
    
    for strategy_name, strategy_func in strategies_map.items():
        if STRATEGIES[strategy_name]['active']:
            try:
                result = strategy_func(indicators)
                if result:
                    direction, score, reason = result
                    all_signals.append({
                        'strategy': strategy_name,
                        'direction': direction,
                        'score': score * STRATEGIES[strategy_name]['weight'],
                        'reason': reason
                    })
            except Exception as e:
                logger.error(f"Erro {strategy_name}: {e}")
    
    return all_signals

def consolidate_signals(signals, symbol):
    """Consolida todos os sinais"""
    if not signals:
        return None
    
    buy_score = 0
    sell_score = 0
    reasons = []
    timeframes = set()
    
    for tf_signal in signals:
        signal = tf_signal['signal']
        weight = tf_signal['weight']
        
        if signal['direction'] == 'COMPRA':
            buy_score += signal['score'] * weight
        else:
            sell_score += signal['score'] * weight
        
        reasons.append(f"{tf_signal['timeframe']}: {signal['reason']}")
        timeframes.add(tf_signal['timeframe'])
    
    # THRESHOLDS BAIXOS PARA MUITOS SINAIS
    min_score = 1.0  # MUITO BAIXO
    min_timeframes = 1
    
    if len(timeframes) >= min_timeframes:
        if buy_score >= min_score:
            return {
                'symbol': symbol,
                'direction': 'COMPRA',
                'price': signals[0]['signal'].get('price', 0),
                'score': buy_score,
                'confidence': min(buy_score / 8.0, 1.0),
                'reasons': reasons[:2],
                'timeframes': list(timeframes),
                'timestamp': datetime.now()
            }
        elif sell_score >= min_score:
            return {
                'symbol': symbol,
                'direction': 'VENDA',
                'price': signals[0]['signal'].get('price', 0),
                'score': sell_score,
                'confidence': min(sell_score / 8.0, 1.0),
                'reasons': reasons[:2],
                'timeframes': list(timeframes),
                'timestamp': datetime.now()
            }
    
    return None

# =========================
# SISTEMA DE SINAIS
# =========================
def check_market_aggressive():
    """Verificação SUPER agressiva"""
    global last_signals
    
    if signals_paused:
        return
    
    logger.info(f"🔍 Verificando {len(PAIRS)} pares AGROSSIVAMENTE...")
    
    signals_found = 0
    
    # Verifica APENAS os 20 pares mais voláteis primeiro
    volatile_pairs = PAIRS[:20]
    
    for symbol in volatile_pairs:
        try:
            # Análise multi-timeframe
            signal = analyze_multi_timeframe(symbol)
            
            if signal:
                # CONFIANÇA MÍNIMA BAIIXA: 40%
                if signal['confidence'] >= 0.4:
                    logger.info(f"✅ {symbol}: {signal['direction']} (Conf: {signal['confidence']:.0%})")
                    
                    # Envia sinal
                    send_signal_telegram(signal)
                    signals_found += 1
                    
                    # Armazena
                    last_signals.append(signal)
                    if len(last_signals) > 100:
                        last_signals.pop(0)
                    
                    # Pequeno delay
                    time.sleep(0.3)
                    
        except Exception as e:
            logger.error(f"Erro {symbol}: {e}")
    
    # Resumo
    if signals_found > 0:
        logger.info(f"🎉 {signals_found} SINAIS ENVIADOS!")
        
        # Se muitos sinais, envia resumo
        if signals_found >= 5:
            send_summary_telegram(signals_found, len(volatile_pairs))
    else:
        logger.info("🔍 Mercado muito neutro - tentando estratégias alternativas...")
        # Tenta pares de medium volatility
        check_medium_volatility_pairs()

def check_medium_volatility_pairs():
    """Verifica pares de média volatilidade"""
    medium_pairs = PAIRS[20:40]
    
    for symbol in medium_pairs[:10]:  # Apenas 10
        try:
            signal = analyze_multi_timeframe(symbol)
            if signal and signal['confidence'] >= 0.45:  # 45% confiança
                send_signal_telegram(signal)
                last_signals.append(signal)
                time.sleep(0.3)
        except:
            pass

def send_signal_telegram(signal):
    """Envia sinal para Telegram"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return False
    
    message = format_signal_message(signal)
    
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
    except:
        return False

def send_summary_telegram(signals_count, pairs_checked):
    """Envia resumo"""
    summary = (
        f"📊 <b>RESUMO RÁPIDO</b>\n"
        f"═══════════════════\n"
        f"✅ Sinais: {signals_count}\n"
        f"🔍 Pares: {pairs_checked}\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}\n"
        f"═══════════════════\n"
        f"<i>Bot ativo e gerando sinais!</i>"
    )
    send_telegram_message(summary)

def send_telegram_message(message):
    """Envia mensagem genérica"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return False
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        requests.post(url, json=data, timeout=5)
        return True
    except:
        return False

def format_signal_message(signal):
    """Formata mensagem bonita"""
    direction_emoji = "🚀" if signal['direction'] == 'COMPRA' else "🔻"
    
    message = (
        f"{direction_emoji} <b>{signal['direction']} AGORA!</b>\n"
        f"═══════════════════\n"
        f"📊 {signal['symbol']}\n"
        f"💰 ${signal['price']:.8f if signal['price'] < 1 else signal['price']:.4f}\n"
        f"🎯 Conf: {signal['confidence']:.0%}\n"
        f"⏰ {signal['timestamp'].strftime('%H:%M:%S')}\n"
    )
    
    if signal.get('reasons'):
        message += f"📝 {signal['reasons'][0]}\n"
    
    message += (
        f"═══════════════════\n"
        f"<i>Bot Alta Frequência</i>"
    )
    
    return message

# =========================
# DASHBOARD WEB
# =========================
@app.route('/')
def dashboard():
    """Dashboard principal"""
    
    uptime = datetime.now() - bot_start_time
    hours = uptime.seconds // 3600
    minutes = (uptime.seconds % 3600) // 60
    
    today = datetime.now().date()
    today_signals = [s for s in last_signals if s['timestamp'].date() == today]
    
    recent_signals = last_signals[-10:] if last_signals else []
    
    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>🤖 Crypto Bot - SINAIS AGORA</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #1a2980 0%, #26d0ce 100%);
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
                box-shadow: 0 10px 20px rgba(0,0,0,0.08);
            }
            .stat-value {
                font-size: 2.5rem;
                font-weight: bold;
                margin: 10px 0;
                color: #2d3748;
            }
            .card {
                background: white;
                border-radius: 20px;
                padding: 30px;
                margin-bottom: 30px;
                box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            }
            .signal {
                padding: 20px;
                margin: 15px 0;
                border-radius: 12px;
                border-left: 5px solid;
            }
            .signal-buy {
                border-left-color: #27ae60;
                background: rgba(39, 174, 96, 0.05);
            }
            .signal-sell {
                border-left-color: #e74c3c;
                background: rgba(231, 76, 60, 0.05);
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
                background: #3498db;
                color: white;
            }
            .btn-success {
                background: #27ae60;
                color: white;
            }
            .btn-danger {
                background: #e74c3c;
                color: white;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🤖 CRYPTO BOT - SINAIS AGORA</h1>
                <p>Gerando sinais em tempo real com estratégias agressivas</p>
                <div>
                    {% if not paused %}
                    <a href="/pause" class="btn btn-danger">⏸️ PAUSAR</a>
                    {% else %}
                    <a href="/resume" class="btn btn-success">▶️ RETOMAR</a>
                    {% endif %}
                    <a href="/check_now" class="btn btn-primary">🔍 VERIFICAR AGORA</a>
                </div>
            </div>
            
            <div class="stats">
                <div class="stat-card">
                    <div>Pares Ativos</div>
                    <div class="stat-value">{{ pairs_count }}</div>
                </div>
                <div class="stat-card">
                    <div>Sinais Hoje</div>
                    <div class="stat-value">{{ today_signals_count }}</div>
                </div>
                <div class="stat-card">
                    <div>Buy/Sell</div>
                    <div class="stat-value">{{ buy_signals }}/{{ sell_signals }}</div>
                </div>
                <div class="stat-card">
                    <div>Uptime</div>
                    <div class="stat-value">{{ uptime_str }}</div>
                </div>
            </div>
            
            <div class="card">
                <h2>📊 Últimos Sinais</h2>
                {% if recent_signals %}
                    {% for signal in recent_signals %}
                    <div class="signal signal-{{ signal.direction|lower }}">
                        <strong>{{ signal.symbol }}</strong> - 
                        <span style="color: {{ 'green' if signal.direction == 'COMPRA' else 'red' }}">
                            {{ signal.direction }}
                        </span>
                        <br>
                        Preço: ${{ "%.4f"|format(signal.price) if signal.price >= 1 else "%.8f"|format(signal.price) }}
                        | Conf: {{ "%.0f"|format(signal.confidence * 100) }}%
                        <br>
                        <small>{{ signal.timestamp.strftime('%H:%M:%S') }}</small>
                    </div>
                    {% endfor %}
                {% else %}
                    <p style="text-align: center; color: #666; padding: 40px;">
                        Aguardando primeiros sinais...<br>
                        Clique em "VERIFICAR AGORA"
                    </p>
                {% endif %}
            </div>
            
            <div class="card">
                <h2>⚡ Configuração Ativa</h2>
                <p><strong>Estratégias:</strong> 12 ativas (super agressivas)</p>
                <p><strong>Timeframes:</strong> 1m, 5m</p>
                <p><strong>Confiança mínima:</strong> 40%</p>
                <p><strong>Pares prioritários:</strong> 20 mais voláteis</p>
                <p><strong>Frequência:</strong> Verificação a cada 60s</p>
            </div>
        </div>
        
        <script>
            setTimeout(() => location.reload(), 30000);
        </script>
    </body>
    </html>
    '''
    
    buy_signals = len([s for s in today_signals if s['direction'] == 'COMPRA'])
    sell_signals = len([s for s in today_signals if s['direction'] == 'VENDA'])
    
    return render_template_string(
        html,
        pairs_count=len(PAIRS),
        today_signals_count=len(today_signals),
        buy_signals=buy_signals,
        sell_signals=sell_signals,
        uptime_str=f"{hours}h {minutes}m",
        recent_signals=recent_signals,
        paused=signals_paused
    )

@app.route('/check_now')
def check_now():
    """Verificação manual"""
    threading.Thread(target=check_market_aggressive).start()
    return '''
    <!DOCTYPE html>
    <html>
    <head><style>
        body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
        background:linear-gradient(135deg,#1a2980 0%,#26d0ce 100%);display:flex;
        justify-content:center;align-items:center;height:100vh;margin:0}
        .message{background:white;padding:50px;border-radius:20px;text-align:center;
        box-shadow:0 20px 40px rgba(0,0,0,0.2);max-width:500px}
        .btn{display:inline-block;padding:14px 28px;background:#3498db;
        color:white;text-decoration:none;border-radius:12px;font-weight:600;margin-top:20px}
    </style></head>
    <body>
        <div class="message">
            <h1>🔍 Verificando AGORA!</h1>
           
