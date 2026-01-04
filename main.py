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
TIMEFRAMES = ['1m', '5m', '15m']  # Multi-timeframe

# 50+ PARES ORGANIZADOS
PAIRS = [
    # Top 10
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT',
    'ADAUSDT', 'AVAXUSDT', 'DOGEUSDT', 'DOTUSDT', 'TRXUSDT',
    
    # Próximos 20
    'LINKUSDT', 'MATICUSDT', 'SHIBUSDT', 'LTCUSDT', 'UNIUSDT',
    'ATOMUSDT', 'ETCUSDT', 'XLMUSDT', 'ALGOUSDT', 'VETUSDT',
    'FILUSDT', 'ICPUSDT', 'NEARUSDT', 'FTMUSDT', 'AAVEUSDT',
    'APEUSDT', 'GRTUSDT', 'SANDUSDT', 'MANAUSDT', 'AXSUSDT',
    
    # Altcoins promissores
    'CRVUSDT', 'MKRUSDT', 'SNXUSDT', 'COMPUSDT', 'YFIUSDT',
    'KAVAUSDT', 'RUNEUSDT', '1INCHUSDT', 'ENJUSDT', 'CHZUSDT',
    
    # Meme & Trending
    'PEPEUSDT', 'FLOKIUSDT', 'BONKUSDT', 'WIFUSDT', 'MEMEUSDT',
    'PENDLEUSDT', 'JTOUSDT', 'JUPUSDT', 'PYTHUSDT', 'ORDIUSDT',
    
    # Mais volume
    'GALAUSDT', 'IMXUSDT', 'RNDRUSDT', 'MINAUSDT', 'SEIUSDT'
]

# ESTRATÉGIAS QUE GERAM MUITOS SINAIS
STRATEGIES = {
    # Alta Frequência (muitos sinais)
    'RSI_EXTREME': {'weight': 1.4, 'active': True, 'type': 'momentum'},
    'STOCH_FAST': {'weight': 1.2, 'active': True, 'type': 'momentum'},
    'PRICE_BREAKOUT': {'weight': 1.5, 'active': True, 'type': 'breakout'},
    'VOLUME_SPIKE_5x': {'weight': 1.3, 'active': True, 'type': 'volume'},
    'SUPPORT_TOUCH': {'weight': 1.1, 'active': True, 'type': 'reversal'},
    'RESISTANCE_TOUCH': {'weight': 1.1, 'active': True, 'type': 'reversal'},
    
    # Média Frequência
    'EMA_9_21_CROSS': {'weight': 1.3, 'active': True, 'type': 'trend'},
    'MACD_QUICK_CROSS': {'weight': 1.2, 'active': True, 'type': 'trend'},
    'BB_SQUEEZE_BREAK': {'weight': 1.4, 'active': True, 'type': 'volatility'},
    'MOMENTUM_REVERSAL': {'weight': 1.3, 'active': True, 'type': 'momentum'},
    
    # Baixa Frequência (confirmação)
    'TREND_ALIGNMENT': {'weight': 1.5, 'active': True, 'type': 'trend'},
    'MULTI_TIMEFRAME': {'weight': 1.6, 'active': True, 'type': 'confirmation'},
}

# =========================
# FUNÇÕES DE ANÁLISE AVANÇADA
# =========================
def get_binance_klines(symbol, interval='1m', limit=100):
    """Obtém candles com cache"""
    try:
        url = f"https://api.binance.com/api/v3/klines"
        params = {'symbol': symbol, 'interval': interval, 'limit': limit}
        response = requests.get(url, params=params, timeout=15)
        
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.error(f"Erro klines {symbol} {interval}: {e}")
    return None

def calculate_indicators(prices, volumes=None):
    """Calcula múltiplos indicadores de uma vez"""
    if len(prices) < 20:
        return {}
    
    # Médias Móveis
    sma20 = sum(prices[-20:]) / 20
    sma50 = sum(prices[-50:]) / 50 if len(prices) >= 50 else sma20
    
    # EMA (simplificada)
    ema9 = calculate_ema_simple(prices, 9)
    ema21 = calculate_ema_simple(prices, 21)
    
    # RSI
    rsi = calculate_rsi_simple(prices)
    
    # Estocástico Rápido
    stochastic = calculate_stochastic_fast(prices)
    
    # Suporte/Resistência dinâmico
    recent_low = min(prices[-20:])
    recent_high = max(prices[-20:])
    
    return {
        'price': prices[-1],
        'sma20': sma20,
        'sma50': sma50,
        'ema9': ema9,
        'ema21': ema21,
        'rsi': rsi,
        'stochastic': stochastic,
        'recent_low': recent_low,
        'recent_high': recent_high,
        'volumes': volumes[-20:] if volumes else None
    }

def calculate_ema_simple(prices, period):
    """EMA simplificada"""
    if len(prices) < period:
        return prices[-1]
    
    multiplier = 2 / (period + 1)
    ema = prices[0]
    
    for price in prices[1:]:
        ema = (price - ema) * multiplier + ema
    
    return ema

def calculate_rsi_simple(prices, period=14):
    """RSI simplificado mas eficiente"""
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

def calculate_stochastic_fast(prices, period=14):
    """Stochastic rápido"""
    if len(prices) < period:
        return 50
    
    recent_low = min(prices[-period:])
    recent_high = max(prices[-period:])
    
    if recent_high == recent_low:
        return 50
    
    current = prices[-1]
    return ((current - recent_low) / (recent_high - recent_low)) * 100

# =========================
# ESTRATÉGIAS DE ALTA FREQUÊNCIA
# =========================
def strategy_rsi_extreme(indicators):
    """RSI em zonas extremas - GERA MUITOS SINAIS"""
    rsi = indicators['rsi']
    
    if rsi < 25:  # Muito oversold
        return ('COMPRA', 1.4, 'RSI EXTREMO OVERSOLD')
    elif rsi > 75:  # Muito overbought
        return ('VENDA', 1.4, 'RSI EXTREMO OVERBOUGHT')
    elif rsi < 32:
        return ('COMPRA', 1.1, 'RSI OVERSOLD')
    elif rsi > 68:
        return ('VENDA', 1.1, 'RSI OVERBOUGHT')
    
    return None

def strategy_stoch_fast(indicators):
    """Stochastic rápido - sinal frequente"""
    stoch = indicators['stochastic']
    
    if stoch < 20:
        return ('COMPRA', 1.2, 'STOCH OVERSOLD')
    elif stoch > 80:
        return ('VENDA', 1.2, 'STOCH OVERBOUGHT')
    elif stoch < 30 and stoch > indicators.get('prev_stoch', 50):
        return ('COMPRA', 0.9, 'STOCH REVERSÃO')
    elif stoch > 70 and stoch < indicators.get('prev_stoch', 50):
        return ('VENDA', 0.9, 'STOCH REVERSÃO')
    
    return None

def strategy_price_breakout(indicators):
    """Breakout de preço - sinal comum"""
    price = indicators['price']
    recent_high = indicators['recent_high']
    recent_low = indicators['recent_low']
    
    # Breakout de resistência
    if price >= recent_high * 0.998:  # 0.2% da resistência
        return ('COMPRA', 1.5, 'BREAKOUT RESISTÊNCIA')
    
    # Breakdown de suporte
    if price <= recent_low * 1.002:  # 0.2% do suporte
        return ('VENDA', 1.5, 'BREAKDOWN SUPORTE')
    
    # Toque em suporte/resistência
    if abs(price - recent_high) / recent_high < 0.003:  # 0.3%
        return ('VENDA', 1.0, 'TOQUE RESISTÊNCIA')
    elif abs(price - recent_low) / recent_low < 0.003:
        return ('COMPRA', 1.0, 'TOQUE SUPORTE')
    
    return None

def strategy_volume_spike_5x(indicators):
    """Spike de volume 5x - sinal forte"""
    if not indicators.get('volumes'):
        return None
    
    volumes = indicators['volumes']
    if len(volumes) < 20:
        return None
    
    current_volume = volumes[-1]
    avg_volume = sum(volumes[-20:]) / 20
    
    if current_volume > avg_volume * 3:  # 3x volume médio
        price = indicators['price']
        prev_price = indicators.get('prev_price', price)
        
        if price > prev_price:
            return ('COMPRA', 1.3, f'VOLUME 3x (+{(current_volume/avg_volume):.1f}x)')
        else:
            return ('VENDA', 1.3, f'VOLUME 3x (+{(current_volume/avg_volume):.1f}x)')
    
    return None

def strategy_ema_cross(indicators):
    """Cruzamento EMA 9/21 - clássico"""
    ema9 = indicators['ema9']
    ema21 = indicators['ema21']
    prev_ema9 = indicators.get('prev_ema9', ema9)
    prev_ema21 = indicators.get('prev_ema21', ema21)
    
    # Golden Cross
    if ema9 > ema21 and prev_ema9 <= prev_ema21:
        return ('COMPRA', 1.3, 'EMA GOLDEN CROSS')
    
    # Death Cross
    if ema9 < ema21 and prev_ema9 >= prev_ema21:
        return ('VENDA', 1.3, 'EMA DEATH CROSS')
    
    # Alinhamento
    if ema9 > ema21 and indicators['price'] > ema9:
        return ('COMPRA', 1.0, 'ALINHAMENTO ALTA')
    elif ema9 < ema21 and indicators['price'] < ema9:
        return ('VENDA', 1.0, 'ALINHAMENTO BAIXA')
    
    return None

def strategy_macd_quick(indicators, prev_indicators=None):
    """MACD rápido - detecta momentum"""
    # Simulação simplificada do MACD
    if len(indicators.get('prices', [])) < 26:
        return None
    
    prices = indicators.get('prices', [])
    
    # EMA 12 e 26
    ema12 = calculate_ema_simple(prices, 12)
    ema26 = calculate_ema_simple(prices, 26)
    macd_line = ema12 - ema26
    
    # Signal line (EMA 9 do MACD)
    if prev_indicators and 'macd_line' in prev_indicators:
        macd_values = prev_indicators.get('macd_history', []) + [macd_line]
        if len(macd_values) > 9:
            signal_line = calculate_ema_simple(macd_values[-9:], 9)
            
            # Cruzamento
            prev_macd = prev_indicators.get('macd_line', macd_line)
            prev_signal = prev_indicators.get('signal_line', signal_line)
            
            if macd_line > signal_line and prev_macd <= prev_signal:
                return ('COMPRA', 1.2, 'MACD BULLISH CROSS')
            elif macd_line < signal_line and prev_macd >= prev_signal:
                return ('VENDA', 1.2, 'MACD BEARISH CROSS')
    
    return None

# =========================
# ANÁLISE MULTI-TIMEFRAME
# =========================
def analyze_multi_timeframe(symbol):
    """Analisa em múltiplos timeframes"""
    timeframe_signals = []
    
    for tf in TIMEFRAMES:
        try:
            klines = get_binance_klines(symbol, interval=tf, limit=100)
            if not klines or len(klines) < 30:
                continue
            
            closes = [float(k[4]) for k in klines]
            volumes = [float(k[5]) for k in klines]
            
            indicators = calculate_indicators(closes, volumes)
            indicators['prices'] = closes
            
            # Aplica estratégias por timeframe
            signals = apply_strategies(indicators)
            
            for signal in signals:
                timeframe_signals.append({
                    'timeframe': tf,
                    'signal': signal,
                    'weight': {'1m': 1.0, '5m': 1.2, '15m': 1.5}[tf]
                })
                
        except Exception as e:
            logger.error(f"Erro timeframe {tf} {symbol}: {e}")
    
    # Consolida sinais de múltiplos timeframes
    return consolidate_timeframe_signals(timeframe_signals, symbol)

def apply_strategies(indicators):
    """Aplica todas as estratégias ativas"""
    signals = []
    
    strategy_functions = {
        'RSI_EXTREME': strategy_rsi_extreme,
        'STOCH_FAST': strategy_stoch_fast,
        'PRICE_BREAKOUT': strategy_price_breakout,
        'VOLUME_SPIKE_5x': strategy_volume_spike_5x,
        'EMA_9_21_CROSS': strategy_ema_cross,
        'MACD_QUICK_CROSS': strategy_macd_quick,
    }
    
    for strategy_name, strategy_func in strategy_functions.items():
        if STRATEGIES[strategy_name]['active']:
            try:
                result = strategy_func(indicators)
                if result:
                    direction, score, reason = result
                    signals.append({
                        'strategy': strategy_name,
                        'direction': direction,
                        'score': score * STRATEGIES[strategy_name]['weight'],
                        'reason': reason
                    })
            except Exception as e:
                logger.error(f"Erro estratégia {strategy_name}: {e}")
    
    return signals

def consolidate_timeframe_signals(timeframe_signals, symbol):
    """Consolida sinais de múltiplos timeframes"""
    if not timeframe_signals:
        return None
    
    buy_score = 0
    sell_score = 0
    reasons = []
    timeframes_used = set()
    
    for tf_signal in timeframe_signals:
        signal = tf_signal['signal']
        weight = tf_signal['weight']
        
        if signal['direction'] == 'COMPRA':
            buy_score += signal['score'] * weight
        else:
            sell_score += signal['score'] * weight
        
        reasons.append(f"{tf_signal['timeframe']}: {signal['reason']}")
        timeframes_used.add(tf_signal['timeframe'])
    
    # Determina direção final
    min_confidence = 2.0  # Reduzido para mais sinais
    min_timeframes = 1    # Aceita 1 timeframe para mais frequência
    
    if len(timeframes_used) >= min_timeframes:
        if buy_score >= min_confidence and buy_score > sell_score:
            return {
                'symbol': symbol,
                'direction': 'COMPRA',
                'price': timeframe_signals[0]['signal'].get('price', 0),
                'score': buy_score,
                'confidence': min(buy_score / 5.0, 1.0),
                'reasons': reasons[:3],  # Top 3 reasons
                'timeframes': list(timeframes_used),
                'timestamp': datetime.now()
            }
        elif sell_score >= min_confidence and sell_score > buy_score:
            return {
                'symbol': symbol,
                'direction': 'VENDA',
                'price': timeframe_signals[0]['signal'].get('price', 0),
                'score': sell_score,
                'confidence': min(sell_score / 5.0, 1.0),
                'reasons': reasons[:3],
                'timeframes': list(timeframes_used),
                'timestamp': datetime.now()
            }
    
    return None

# =========================
# SISTEMA DE SINAIS OTIMIZADO
# =========================
def check_market_optimized():
    """Verificação otimizada para mais sinais"""
    global last_signals
    
    if signals_paused:
        return
    
    logger.info(f"🔍 Verificando {len(PAIRS)} pares em multi-timeframe...")
    
    signals_found = 0
    checked_pairs = 0
    
    # Verifica pares em batches para performance
    batch_size = 5
    for i in range(0, len(PAIRS), batch_size):
        batch = PAIRS[i:i+batch_size]
        
        for symbol in batch:
            try:
                checked_pairs += 1
                
                # Análise multi-timeframe
                signal = analyze_multi_timeframe(symbol)
                
                if signal:
                    logger.info(f"✅ {symbol}: {signal['direction']} (Score: {signal['score']:.1f})")
                    
                    # Envia sinal se confiança > 50%
                    if signal['confidence'] >= 0.5:  # Reduzido para mais sinais
                        send_signal(signal)
                        signals_found += 1
                        
                        # Pequeno delay entre sinais
                        time.sleep(0.5)
                        
            except Exception as e:
                logger.error(f"Erro {symbol}: {e}")
        
        # Delay entre batches
        time.sleep(1)
    
    # Resumo
    if signals_found > 0:
        logger.info(f"📤 {signals_found} sinais enviados!")
        
        # Envia resumo se muitos sinais
        if signals_found >= 3:
            send_summary(signals_found, checked_pairs)
    else:
        logger.info("📭 Nenhum sinal forte encontrado")
        
        # Envia status mesmo sem sinais (opcional)
        if random.random() < 0.3:  # 30% chance
            send_no_signals_status(checked_pairs)

def send_signal(signal):
    """Envia sinal formatado"""
    message = format_signal_message(signal)
    
    if send_telegram_message(message):
        # Armazena sinal
        last_signals.append(signal)
        
        # Mantém histórico
        if len(last_signals) > 100:
            last_signals.pop(0)

def send_summary(signals_count, pairs_checked):
    """Envia resumo de sinais"""
    summary = (
        f"📊 <b>RESUMO DA VERIFICAÇÃO</b>\n"
        f"═══════════════════\n"
        f"✅ Sinais encontrados: {signals_count}\n"
        f"🔍 Pares verificados: {pairs_checked}\n"
        f"⏰ Hora: {datetime.now().strftime('%H:%M:%S')}\n"
        f"📈 Status: Mercado ativo\n"
        f"═══════════════════\n"
        f"<i>Próxima verificação em 1 minuto</i>"
    )
    send_telegram_message(summary)

def send_no_signals_status(pairs_checked):
    """Status quando não há sinais"""
    status = (
        f"🔍 <b>VERIFICAÇÃO CONCLUÍDA</b>\n"
        f"═══════════════════\n"
        f"📭 Sinais encontrados: 0\n"
        f"🔍 Pares verificados: {pairs_checked}\n"
        f"⏰ Hora: {datetime.now().strftime('%H:%M:%S')}\n"
        f"📊 Status: Mercado neutro\n"
        f"═══════════════════\n"
        f"<i>Aguardando oportunidades...</i>"
    )
    send_telegram_message(status)

def format_signal_message(signal):
    """Formata mensagem do sinal"""
    direction_emoji = "🚀" if signal['direction'] == 'COMPRA' else "🔻"
    timeframe_str = "/".join(signal.get('timeframes', ['1m']))
    
    message = (
        f"{direction_emoji} <b>SINAL DE {signal['direction']}</b>\n"
        f"═══════════════════\n"
        f"📊 <b>Par:</b> <code>{signal['symbol']}</code>\n"
        f"⏰ <b>Timeframe:</b> {timeframe_str}\n"
        f"💰 <b>Preço:</b> ${signal['price']:.8f if signal['price'] < 1 else signal['price']:.4f}\n"
        f"🎯 <b>Confiança:</b> {signal['confidence']:.0%}\n"
        f"📈 <b>Score:</b> {signal['score']:.1f}/10\n"
    )
    
    # Adiciona razões
    if signal.get('reasons'):
        message += f"📝 <b>Razões:</b>\n"
        for reason in signal['reasons'][:2]:  # Máximo 2 razões
            message += f"• {reason}\n"
    
    message += (
        f"═══════════════════\n"
        f"⚡ <i>Multi-timeframe | Alta Frequência</i>"
    )
    
    return message

def send_telegram_message(message):
    """Envia mensagem para Telegram"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
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
        logger.error(f"Erro Telegram: {e}")
        return False

# =========================
# DASHBOARD ATUALIZADO
# =========================
@app.route('/')
def dashboard():
    """Dashboard com estatísticas expandidas"""
    
    # Estatísticas
    uptime = datetime.now() - bot_start_time
    hours = uptime.seconds // 3600
    minutes = (uptime.seconds % 3600) // 60
    
    today = datetime.now().date()
    today_signals = [s for s in last_signals if s['timestamp'].date() == today]
    
    # Sinais por estratégia
    strategy_stats = {}
    for signal in today_signals:
        for reason in signal.get('reasons', []):
            strat = reason.split(':')[0] if ':' in reason else 'Geral'
            strategy_stats[strat] = strategy_stats.get(strat, 0) + 1
    
    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Crypto Bot Pro - Alta Frequência</title>
        <style>
            :root {
                --primary: #3498db;
                --success: #27ae60;
                --danger: #e74c3c;
                --warning: #f39c12;
                --purple: #9b59b6;
            }
            
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #1a2980 0%, #26d0ce 100%);
                color: #333;
                margin: 0;
                padding: 20px;
                min-height: 100vh;
            }
            
            .container {
                max-width: 1600px;
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
            
            .dashboard-grid {
                display: grid;
                grid-template-columns: 2fr 1fr;
                gap: 30px;
                margin-bottom: 30px;
            }
            
            @media (max-width: 1200px) {
                .dashboard-grid {
                    grid-template-columns: 1fr;
                }
            }
            
            .card {
                background: white;
                border-radius: 20px;
                padding: 30px;
                box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                margin-bottom: 30px;
            }
            
            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                gap: 20px;
                margin: 20px 0;
            }
            
            .stat-card {
                background: #f8f9fa;
                border-radius: 15px;
                padding: 20px;
                text-align: center;
                transition: transform 0.3s;
            }
            
            .stat-card:hover {
                transform: translateY(-5px);
            }
            
            .stat-value {
                font-size: 2rem;
                font-weight: bold;
                margin: 10px 0;
                color: #2d3748;
            }
            
            .stat-label {
                color: #718096;
                font-size: 0.9rem;
                text-transform: uppercase;
                letter-spacing: 1px;
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
            
            .btn-success {
                background: var(--success);
                color: white;
            }
            
            .btn-danger {
                background: var(--danger);
                color: white;
            }
            
            .btn-purple {
                background: var(--purple);
                color: white;
            }
            
            .btn:hover {
                transform: translateY(-2px);
                box-shadow: 0 10px 20px rgba(0,0,0,0.15);
            }
            
            .timeframe-badge {
                display: inline-block;
                padding: 4px 10px;
                background: #e3f2fd;
                color: var(--primary);
                border-radius: 20px;
                font-size: 0.8rem;
                margin: 2px;
            }
            
            .strategy-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
                gap: 15px;
                margin: 20px 0;
            }
            
            .strategy-item {
                padding: 15px;
                background: #f8f9fa;
                border-radius: 10px;
                text-align: center;
            }
            
            .active {
                background: #e8f5e9;
                color: var(--success);
                border-left: 4px solid var(--success);
            }
            
            .inactive {
                background: #ffebee;
                color: var(--danger);
                border-left: 4px solid var(--danger);
            }
            
            .pairs-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
                gap: 10px;
                margin: 20px 0;
                max-height: 300px;
                overflow-y: auto;
            }
            
            .pair-item {
                padding: 10px;
                background: #e9ecef;
                border-radius: 8px;
                text-align: center;
                font-size: 0.85rem;
            }
            
            .pair-item:hover {
                background: #dee2e6;
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
                transition: width 0.5s;
            }
            
            .buy-fill {
                background: var(--success);
            }
            
            .sell-fill {
                background: var(--danger);
            }
        </style>
    </head>
    <body>
        <div class="container">
            <!-- Header -->
            <div class="header">
                <h1 style="font-size: 2.5rem; margin-bottom: 10px; color: #2d3748;">
                    🤖 Crypto Bot Pro - ALTA FREQUÊNCIA
                </h1>
                <p style="color: #718096; margin-bottom: 20px;">
                    Multi-timeframe | 50+ pares | Estratégias agressivas
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
                    <a href="/force_check" class="btn btn-primary">
                        🔍 Forçar Verificação
                    </a>
                    <a href="/config" class="btn btn-purple">
                        ⚙️ Configurar
                    </a>
                    <a href="/stats" class="btn" style="background: #f39c12; color: white;">
                        📊 Estatísticas
                    </a>
                </div>
            </div>
            
            <!-- Stats Overview -->
            <div class="card">
                <h2>📈 Visão Geral do Sistema</h2>
                
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-label">Pares Ativos</div>
                        <div class="stat-value">{{ pairs_count }}</div>
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
                        <div class="stat-label">Timeframes</div>
                        <div class="stat-value">{{ timeframes_count }}</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Uptime</div>
                        <div class="stat-value">{{ uptime_str }}</div>
                    </div>
                </div>
                
                <div style="margin-top: 30px; padding: 20px; background: #f8f9fa; border-radius: 15px;">
                    <h3>⚡ Configuração Ativa</h3>
                    <p><strong>Timeframes:</strong> {{ timeframes_list }}</p>
                    <p><strong>Estratégias ativas:</strong> {{ active_strategies }}/{{ total_strategies }}</p>
                    <p><strong>Frequência:</strong> Verificação a cada 1 minuto</p>
                    <p><strong>Confiança mínima:</strong> 50%</p>
                </div>
            </div>
            
            <!-- Main Dashboard -->
            <div class="dashboard-grid">
                <!-- Sinais Recentes -->
                <div class="card">
                    <h2>📊 Sinais Recentes (Últimas 2 horas)</h2>
                    
                    {% if recent_signals %}
                        {% for signal in recent_signals %}
                        <div class="signal-item signal-{{ signal.direction|lower }}">
                            <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                                <div>
                                    <strong style="font-size: 1.3rem;">{{ signal.symbol }}</strong>
                                    <span style="margin-left: 10px; padding: 4px 12px; 
                                          background: {{ 'rgba(39, 174, 96, 0.1)' if signal.direction == 'COMPRA' else 'rgba(231, 76, 60, 0.1)' }};
                                          color: {{ '#27ae60' if signal.direction == 'COMPRA' else '#e74c3c' }};
                                          border-radius: 20px; font-weight: 600;">
                                        {{ signal.direction }}
                                    </span>
                                    {% for tf in signal.get('timeframes', ['1m']) %}
                                    <span class="timeframe-badge">{{ tf }}</span>
                                    {% endfor %}
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
                                    <div class="progress-fill {{ 'buy-fill' if signal.direction == 'COMPRA' else 'sell-fill' }}" 
                                         style="width: {{ signal.confidence * 100 }}%">
                                    </div>
                                </div>
                                <div style="display: flex; justify-content: space-between; margin-top: 5px; font-size: 0.9rem;">
                                    <span>🎯 {{ "%.0f"|format(signal.confidence * 100) }}% confiança</span>
                                    <span>📈 Score: {{ "%.1f"|format(signal.score) }}</span>
                                </div>
                            </div>
                            
                            {% if signal.reasons %}
                            <div style="margin-top: 10px; font-size: 0.85rem; color: #5a6268;">
                                <strong>Razões:</strong> {{ signal.reasons|join(' • ') }}
                            </div>
                            {% endif %}
                        </div>
                        {% endfor %}
                    {% else %}
                        <div style="text-align: center; padding: 60px 20px; color: #a0aec0;">
                            <div style="font-size: 4rem; margin-bottom: 20px;">📭</div>
                            <p style="font-size: 1.3rem; margin-bottom: 10px;">Nenhum sinal recente</p>
                            <p>O bot está analisando o mercado. Clique em "Forçar Verificação".</p>
                        </div>
                    {% endif %}
                </div>
                
                <!-- Sidebar -->
                <div style="display: flex; flex-direction: column; gap: 30px;">
                    <!-- Status -->
                    <div class="card">
                        <h3>📈 Status do Sistema</h3>
                        <div style="background: {{ '#e8f5e9' if not paused else '#ffebee' }};
                             padding: 20px; border-radius: 12px; margin: 15px 0; text-align: center;">
                            <div style="font-size: 1.8rem; margin-bottom: 10px;">
                                {% if not paused %}
                                🟢 ATIVO E ANALISANDO
                                {% else %}
                                🔴 SISTEMA PAUSADO
                                {% endif %}
                            </div>
                            <div style="color: #718096;">
                                {{ status_message }}
                            </div>
                        </div>
                        
                        <div style="margin-top: 20px;">
                            <p><strong>📅 Hoje:</strong> {{ today_date }}</p>
                            <p><strong>⏰ Hora atual:</strong> {{ current_time }}</p>
                            <p><strong>🔄 Próxima verificação:</strong> {{ next_check }}</p>
                            <p><strong>📱 Telegram:</strong> {{ telegram_status }}</p>
                        </div>
                    </div>
                    
                    <!-- Estratégias Ativas -->
                    <div class="card">
                        <h3>⚡ Estratégias Ativas</h3>
                        <div class="strategy-grid">
                            {% for name, config in strategies.items() %}
                            <div class="strategy-item {{ 'active' if config.active else 'inactive' }}">
                                <div style="font-weight: bold; margin-bottom: 5px;">
                                    {{ name.replace('_', ' ').title() }}
                                </div>
                                <div style="font-size: 0.8rem; color: #666;">
                                    Peso: {{ config.weight }}<br>
                                    Tipo: {{ config.type }}
                                </div>
                            </div>
                            {% endfor %}
                        </div>
                    </div>
                    
                    <!-- Pares Monitorados -->
                    <div class="card">
                        <h3>🏷️ Pares ({{ pairs_count }})</h3>
                        <div class="pairs-grid">
                            {% for pair in pairs %}
                            <div class="pair-item">
                                {{ pair }}
                            </div>
                            {% endfor %}
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Footer -->
            <div style="text-align: center; color: white; margin-top: 40px; opacity: 0.9;">
                <p>⚡ Sistema de Alta Frequência | 🔄 Auto-atualização em 30s</p>
                <p>🤖 {{ pairs_count }} pares | ⏰ {{ timeframes_count }} timeframes | ⚙️ {{ active_strategies }} estratégias</p>
                <p style="font-size: 0.9rem; margin-top: 10px; opacity: 0.7;">
                    Última atualização: {{ current_time_full }}
                </p>
            </div>
        </div>
        
        <script>
            // Auto-refresh rápido
            setTimeout(() => location.reload(), 30000);
            
            // Anima progress bars
            document.addEventListener('DOMContentLoaded', () => {
                const progressBars = document.querySelectorAll('.progress-fill');
                progressBars.forEach(bar => {
                    const width = bar.style.width;
                    bar.style.width = '0';
                    setTimeout(() => {
                        bar.style.width = width;
                    }, 300);
                });
                
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
            });
        </script>
    </body>
    </html>
    '''
    
    # Calcula estatísticas
    buy_signals = len([s for s in today_signals if s['direction'] == 'COMPRA'])
    sell_signals = len([s for s in today_signals if s['direction'] == 'VENDA'])
    
    avg_confidence = 0
    if today_signals:
        avg_confidence = sum(s['confidence'] for s in today_signals) / len(today_signals) * 100
    
    # Sinais recentes (últimas 2 horas)
    recent_signals = [s for s in last_signals if s['timestamp'] > datetime.now() - timedelta(hours=2)]
    recent_signals.sort(key=lambda x: x['timestamp'], reverse=True)
    
    # Próxima verificação
    next_check = datetime.now() + timedelta(seconds=60)
    
    return render_template_string(
        html,
        pairs_count=len(PAIRS),
        pairs=PAIRS[:30],  # Mostra apenas 30 no grid
        today_signals_count=len(today_signals),
        buy_signals=buy_signals,
        sell_signals=sell_signals,
        avg_confidence=f"{avg_confidence:.1f}",
        uptime_str=f"{hours}h {minutes}m",
        timeframes_count=len(TIMEFRAMES),
        timeframes_list=", ".join(TIMEFRAMES),
        active_strategies=sum(1 for s in STRATEGIES.values() if s['active']),
        total_strategies=len(STRATEGIES),
        recent_signals=recent_signals[:8],
        paused=signals_paused,
        status_message="Analisando mercado em tempo real" if not signals_paused else "Sistema pausado manualmente",
        today_date=datetime.now().strftime('%d/%m/%Y'),
        current_time=datetime.now().strftime('%H:%M'),
        current_time_full=datetime.now().strftime('%H:%M:%S'),
        next_check=next_check.strftime('%H:%M:%S'),
        telegram_status="✅ Conectado" if TELEGRAM_TOKEN and CHAT_ID else "❌ Não configurado",
        strategies=STRATEGIES
    )

# =========================
# ROTAS ADICIONAIS
# =========================
@app.route('/force_check')
def force_check():
    """Força uma verificação imediata"""
    threading.Thread(target=check_market_optimized).start()
    
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
            <h1>🔍 Verificação Forçada</h1>
            <p>O bot está verificando todos os pares agora.</p>
            <p>Verifique seu Telegram em instantes.</p>
            <a href="/" class="btn">← Voltar ao Dashboard</a>
        </div>
    </body>
    </html>
    '''

@app.route('/config')
def config_page():
    """Página de configuração"""
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #1a2980 0%, #26d0ce 100%);
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
            .config-section {
                margin: 30px 0;
                padding: 25px;
                background: #f8f9fa;
                border-radius: 15px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-btn">← Voltar</a>
            <h1>⚙️ Configuração do Sistema</h1>
            
            <div class="config-section">
                <h3>📊 Configuração Atual</h3>
                <p><strong>Pares:</strong> 50+</p>
                <p><strong>Timeframes:</strong> 1m, 5m, 15m</p>
                <p><strong>Estratégias ativas:</strong> 10</p>
                <p><strong>Frequência:</strong> 1 minuto</p>
                <p><strong>Confiança mínima:</strong> 50%</p>
            </div>
            
            <div class="config-section">
                <h3>🎯 Para MAIS sinais:</h3>
                <p>1. Ative todas as estratégias</p>
                <p>2. Reduza confiança mínima para 40%</p>
                <p>3. Adicione mais pares voláteis</p>
                <p>4. Use apenas timeframe 1m</p>
            </div>
            
            <div class="config-section">
                <h3>✅ Para sinais MELHORES:</h3>
                <p>1. Aumente confiança para 60%</p>
                <p>2. Use multi-timeframe (1m, 5m, 15m)</p>
                <p>3. Foque em pares líquidos</p>
                <p>4. Ative estratégias de confirmação</p>
            </div>
        </div>
    </body>
    </html>
    '''

@app.route('/stats')
def stats_page():
    """Página de estatísticas detalhadas"""
    today = datetime.now().date()
    today_signals = [s for s in last_signals if s['timestamp'].date() == today]
    
    # Estatísticas por hora
    hourly_stats = {}
    for hour in range(24):
        hour_signals = [s for s in today_signals if s['timestamp'].hour == hour]
        hourly_stats[hour] = len(hour_signals)
    
    # Top pares
    pair_stats = {}
    for signal in today_signals:
        pair_stats[signal['symbol']] = pair_stats.get(signal['symbol'], 0) + 1
    
    top_pairs = sorted(pair_stats.items(), key=lambda x: x[1], reverse=True)[:10]
    
    return jsonify({
        'today': {
            'total_signals': len(today_signals),
            'buy_signals': len([s for s in today_signals if s['direction'] == 'COMPRA']),
            'sell_signals': len([s for s in today_signals if s['direction'] == 'VENDA']),
            'avg_confidence': sum(s['confidence'] for s in today_signals) / len(today_signals) * 100 if today_signals else 0,
            'hourly_distribution': hourly_stats,
            'top_pairs': dict(top_pairs)
        },
        'system': {
            'pairs_count': len(PAIRS),
            'active_strategies': sum(1 for s in STRATEGIES.values() if s['active']),
            'uptime': str(datetime.now() - bot_start_time),
            'last_signals_count': len(last_signals)
        }
    })

# =========================
# INICIALIZAÇÃO
# =========================
def run_bot():
    """Loop principal otimizado"""
    logger.info("=" * 60)
    logger.info("🤖 CRYPTO BOT PRO - ALTA FREQUÊNCIA")
    logger.info("=" * 60)
    logger.info(f"📊 Pares: {len(PAIRS)}")
    logger.info(f"⏰ Timeframes: {', '.join(TIMEFRAMES)}")
    logger.info(f"🎯 Estratégias: {sum(1 for s in STRATEGIES.values() if s['active'])}")
    logger.info(f"⚡ Confiança mínima: 50%")
    logger.info(f"🔁 Frequência: 60 segundos")
    logger.info("=" * 60)
    
    # Mensagem inicial
    if TELEGRAM_TOKEN and CHAT_ID:
        init_msg = (
            f"🚀 <b>BOT PRO INICIADO - ALTA FREQUÊNCIA</b>\n"
            f"═══════════════════\n"
            f"📊 Pares: {len(PAIRS)}\n"
            f"⏰ Timeframes: {', '.join(TIMEFRAMES)}\n"
            f"🎯 Estratégias: {sum(1 for s in STRATEGIES.values() if s['active'])}\n"
            f"⚡ Confiança mínima: 50%\n"
            f"🔁 Frequência: 60s\n"
            f"═══════════════════\n"
            f"<i>Pronto para gerar sinais!</i>"
        )
        send_telegram_message(init_msg)
    
    # Loop principal
    while True:
        try:
            if not signals_paused:
                check_market_optimized()
            
            time.sleep(60)  # 1 minuto
            
        except Exception as e:
            logger.error(f"Erro loop principal: {e}")
            time.sleep(30)

def main():
    """Função principal"""
    
    # Inicia bot em thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Inicia servidor
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"🌐 Dashboard: http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)

if __name__ == "__main__":
    main()
