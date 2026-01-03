import telebot
import requests
import pandas as pd
import numpy as np
import time
import schedule
import threading
from flask import Flask, render_template_string, jsonify, request
import os
from datetime import datetime, timedelta
import logging
import warnings
warnings.filterwarnings('ignore')

# =========================
# CONFIGURAÇÃO DE LOG
# =========================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# =========================
# CONFIGURAÇÕES
# =========================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

if not TELEGRAM_TOKEN or not CHAT_ID:
    raise ValueError("Configure TELEGRAM_TOKEN e CHAT_ID como variáveis de ambiente")

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode='HTML')

# Estados do bot
signals_paused = False
last_signals = []
signal_cache = {}
bot_start_time = datetime.now()

# =========================
# LISTA DE PARES (versão simplificada)
# =========================
PAIRS = [
    # Top 20 principais
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT',
    'ADAUSDT', 'AVAXUSDT', 'DOGEUSDT', 'DOTUSDT', 'TRXUSDT',
    'LINKUSDT', 'MATICUSDT', 'SHIBUSDT', 'LTCUSDT', 'UNIUSDT',
    'ATOMUSDT', 'ETCUSDT', 'XLMUSDT', 'ALGOUSDT', 'VETUSDT'
]

# =========================
# ESTRATÉGIAS (versão simplificada sem TA-Lib)
# =========================
STRATEGIES = {
    # Estratégias básicas
    'ema_crossover': {'weight': 1.2, 'active': True},
    'rsi_scalping': {'weight': 1.1, 'active': True},
    'macd_crossover': {'weight': 1.0, 'active': True},
    'bollinger_bands': {'weight': 0.9, 'active': True},
    'vwap_strategy': {'weight': 1.0, 'active': True},
    'volume_spike': {'weight': 0.8, 'active': True},
    'support_resistance': {'weight': 1.1, 'active': True}
}

# =========================
# FUNÇÕES UTILITÁRIAS
# =========================
def format_price(price: float, symbol: str) -> str:
    """Formata preço baseado no par"""
    if price >= 1000:
        return f"{price:.1f}"
    elif price >= 100:
        return f"{price:.2f}"
    elif price >= 10:
        return f"{price:.3f}"
    elif price >= 1:
        return f"{price:.4f}"
    else:
        return f"{price:.6f}"

def get_uptime() -> str:
    """Calcula tempo de atividade do bot"""
    uptime = datetime.now() - bot_start_time
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    if days > 0:
        return f"{days}d {hours}h"
    return f"{hours}h {minutes}m"

def calculate_ema(series, period):
    """Calcula EMA sem TA-Lib"""
    return series.ewm(span=period, adjust=False).mean()

def calculate_rsi(series, period=14):
    """Calcula RSI sem TA-Lib"""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_macd(series, fast=12, slow=26, signal=9):
    """Calcula MACD sem TA-Lib"""
    ema_fast = calculate_ema(series, fast)
    ema_slow = calculate_ema(series, slow)
    macd = ema_fast - ema_slow
    signal_line = calculate_ema(macd, signal)
    return macd, signal_line

# =========================
# FUNÇÃO PARA DADOS DA BINANCE
# =========================
def get_binance_data(symbol: str, interval: str = '1m', limit: int = 100) -> Optional[pd.DataFrame]:
    """Obtém dados da Binance"""
    try:
        url = 'https://api.binance.com/api/v3/klines'
        params = {'symbol': symbol, 'interval': interval, 'limit': limit}
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        if not data:
            return None
            
        df = pd.DataFrame(data, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'qav', 'trades', 'tbb', 'tbq', 'ignore'
        ])
        
        # Conversão de tipos
        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        df[numeric_cols] = df[numeric_cols].astype(float)
        df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
        df.set_index('open_time', inplace=True)
        
        return df
        
    except Exception as e:
        logger.error(f"Erro ao obter dados para {symbol}: {e}")
        return None

# =========================
# ESTRATÉGIAS IMPLEMENTADAS
# =========================
def ema_crossover_strategy(df: pd.DataFrame) -> Optional[str]:
    """EMA 9/21 Crossover"""
    try:
        df['EMA9'] = calculate_ema(df['close'], 9)
        df['EMA21'] = calculate_ema(df['close'], 21)
        
        last, prev = df.iloc[-1], df.iloc[-2]
        
        # Golden Cross
        if last['EMA9'] > last['EMA21'] and prev['EMA9'] <= prev['EMA21']:
            return 'buy'
        
        # Death Cross
        if last['EMA9'] < last['EMA21'] and prev['EMA9'] >= prev['EMA21']:
            return 'sell'
            
    except Exception as e:
        logger.error(f"Erro EMA Crossover: {e}")
    return None

def rsi_scalping_strategy(df: pd.DataFrame) -> Optional[str]:
    """RSI para scalping"""
    try:
        df['RSI'] = calculate_rsi(df['close'], 14)
        rsi_val = df['RSI'].iloc[-1]
        
        if rsi_val < 30:
            return 'buy'
        elif rsi_val > 70:
            return 'sell'
            
    except Exception as e:
        logger.error(f"Erro RSI: {e}")
    return None

def macd_crossover_strategy(df: pd.DataFrame) -> Optional[str]:
    """MACD Crossover"""
    try:
        macd_line, signal_line = calculate_macd(df['close'])
        df['MACD'] = macd_line
        df['MACD_SIGNAL'] = signal_line
        
        last, prev = df.iloc[-1], df.iloc[-2]
        
        # Bullish crossover
        if prev['MACD'] < prev['MACD_SIGNAL'] and last['MACD'] > last['MACD_SIGNAL']:
            return 'buy'
        
        # Bearish crossover
        if prev['MACD'] > prev['MACD_SIGNAL'] and last['MACD'] < last['MACD_SIGNAL']:
            return 'sell'
            
    except Exception as e:
        logger.error(f"Erro MACD: {e}")
    return None

def bollinger_bands_strategy(df: pd.DataFrame) -> Optional[str]:
    """Bollinger Bands"""
    try:
        period = 20
        df['BB_MIDDLE'] = df['close'].rolling(window=period).mean()
        std = df['close'].rolling(window=period).std()
        df['BB_UPPER'] = df['BB_MIDDLE'] + (std * 2)
        df['BB_LOWER'] = df['BB_MIDDLE'] - (std * 2)
        
        last_close = df['close'].iloc[-1]
        last_upper = df['BB_UPPER'].iloc[-1]
        last_lower = df['BB_LOWER'].iloc[-1]
        
        # Tocar banda inferior
        if last_close <= last_lower:
            return 'buy'
        
        # Tocar banda superior
        if last_close >= last_upper:
            return 'sell'
            
    except Exception as e:
        logger.error(f"Erro Bollinger Bands: {e}")
    return None

def vwap_strategy(df: pd.DataFrame) -> Optional[str]:
    """Volume Weighted Average Price"""
    try:
        # Calcula VWAP
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        vwap = (typical_price * df['volume']).cumsum() / df['volume'].cumsum()
        df['VWAP'] = vwap
        
        last_close = df['close'].iloc[-1]
        last_vwap = df['VWAP'].iloc[-1]
        prev_close = df['close'].iloc[-2]
        prev_vwap = df['VWAP'].iloc[-2]
        
        # Cruzamento acima do VWAP
        if prev_close <= prev_vwap and last_close > last_vwap:
            return 'buy'
        
        # Cruzamento abaixo do VWAP
        if prev_close >= prev_vwap and last_close < last_vwap:
            return 'sell'
            
    except Exception as e:
        logger.error(f"Erro VWAP: {e}")
    return None

def volume_spike_strategy(df: pd.DataFrame) -> Optional[str]:
    """Detecta spikes de volume"""
    try:
        volume_ma = df['volume'].rolling(20).mean()
        df['VOLUME_MA'] = volume_ma
        
        last_volume = df['volume'].iloc[-1]
        last_volume_ma = df['VOLUME_MA'].iloc[-1]
        last_close = df['close'].iloc[-1]
        prev_close = df['close'].iloc[-2]
        
        # Volume spike com candle bullish
        if last_volume > last_volume_ma * 2.0 and last_close > prev_close:
            return 'buy'
        
        # Volume spike com candle bearish
        if last_volume > last_volume_ma * 2.0 and last_close < prev_close:
            return 'sell'
            
    except Exception as e:
        logger.error(f"Erro Volume Spike: {e}")
    return None

def support_resistance_strategy(df: pd.DataFrame) -> Optional[str]:
    """Suporte e Resistência"""
    try:
        if len(df) < 30:
            return None
        
        # Identifica máximos e mínimos
        lookback = 30
        recent_high = df['high'].rolling(window=lookback).max().iloc[-1]
        recent_low = df['low'].rolling(window=lookback).min().iloc[-1]
        
        current_price = df['close'].iloc[-1]
        tolerance = current_price * 0.005  # 0.5%
        
        # Teste de resistência
        if abs(current_price - recent_high) <= tolerance:
            # Rejeição na resistência
            if df['high'].iloc[-1] >= recent_high and df['close'].iloc[-1] < recent_high:
                return 'sell'
        
        # Teste de suporte
        if abs(current_price - recent_low) <= tolerance:
            # Rejeição no suporte
            if df['low'].iloc[-1] <= recent_low and df['close'].iloc[-1] > recent_low:
                return 'buy'
                
    except Exception as e:
        logger.error(f"Erro Support/Resistance: {e}")
    return None

# =========================
# FILTROS
# =========================
def volume_filter(df: pd.DataFrame) -> bool:
    """Filtro de volume"""
    try:
        if len(df) < 20:
            return False
            
        current_volume = df['volume'].iloc[-1]
        avg_volume = df['volume'].rolling(20).mean().iloc[-1]
        return current_volume > avg_volume * 1.2
    except:
        return False

def is_signal_duplicate(symbol: str, direction: str) -> bool:
    """Verifica se sinal é duplicado"""
    cache_key = f"{symbol}_{direction}"
    current_time = datetime.now()
    
    if cache_key in signal_cache:
        last_time = signal_cache[cache_key]
        if current_time - last_time < timedelta(minutes=5):
            return True
    
    signal_cache[cache_key] = current_time
    return False

# =========================
# GERAÇÃO DE SINAL
# =========================
def generate_signal(df: pd.DataFrame, symbol: str) -> Optional[str]:
    """Gera sinal combinando estratégias"""
    try:
        if not volume_filter(df):
            return None
        
        # Executa estratégias ativas
        signals = {}
        strategy_functions = {
            'ema_crossover': ema_crossover_strategy,
            'rsi_scalping': rsi_scalping_strategy,
            'macd_crossover': macd_crossover_strategy,
            'bollinger_bands': bollinger_bands_strategy,
            'vwap_strategy': vwap_strategy,
            'volume_spike': volume_spike_strategy,
            'support_resistance': support_resistance_strategy
        }
        
        for strategy_name, strategy_func in strategy_functions.items():
            if STRATEGIES[strategy_name]['active']:
                try:
                    signals[strategy_name] = strategy_func(df)
                except Exception as e:
                    logger.error(f"Erro na estratégia {strategy_name}: {e}")
                    signals[strategy_name] = None
        
        # Contagem ponderada
        buy_score = 0
        sell_score = 0
        contributing_strategies = []
        
        for strategy_name, result in signals.items():
            if result:
                weight = STRATEGIES[strategy_name]['weight']
                
                if result == 'buy':
                    buy_score += weight
                    contributing_strategies.append(strategy_name)
                elif result == 'sell':
                    sell_score += weight
                    contributing_strategies.append(strategy_name)
        
        # Determina direção
        confidence_threshold = 1.5
        
        if buy_score >= confidence_threshold and not is_signal_duplicate(symbol, 'buy'):
            direction = 'COMPRA'
            emoji = '🚀'
            tp_mult = 1.003
            sl_mult = 0.998
            confidence_score = buy_score
        elif sell_score >= confidence_threshold and not is_signal_duplicate(symbol, 'sell'):
            direction = 'VENDA'
            emoji = '🔻'
            tp_mult = 0.997
            sl_mult = 1.002
            confidence_score = sell_score
        else:
            return None
        
        entry = df['close'].iloc[-1]
        tp = entry * tp_mult
        sl = entry * sl_mult
        
        # Formata mensagem
        formatted_entry = format_price(entry, symbol)
        formatted_tp = format_price(tp, symbol)
        formatted_sl = format_price(sl, symbol)
        
        signal_text = (
            f"{emoji} <b>SCALPING {direction}</b>\n"
            f"📊 Par: <code>{symbol}</code>\n"
            f"💰 Entrada: <b>{formatted_entry}</b>\n"
            f"🎯 TP: {formatted_tp} (+0.3%)\n"
            f"🛡️ SL: {formatted_sl} (-0.2%)\n"
            f"⏰ TF: 1m | 📈 Volume: Confirmado\n"
            f"🧮 Estratégias: {len(contributing_strategies)}/{len(signals)}\n"
            f"📊 Confiança: {confidence_score:.1f}/5.0\n"
            f"🕐 Hora: {datetime.now().strftime('%H:%M:%S')}\n"
        )
        
        # Adiciona estratégias contribuintes
        if contributing_strategies:
            strategy_names = [s.replace('_', ' ').title() for s in contributing_strategies]
            signal_text += f"🏆 Estratégias: {', '.join(strategy_names[:3])}"
        
        # Armazena sinal
        signal_data = {
            'time': datetime.now(),
            'symbol': symbol,
            'direction': direction,
            'entry': entry,
            'tp': tp,
            'sl': sl,
            'confidence': confidence_score,
            'strategies_used': len(contributing_strategies),
            'text': signal_text
        }
        
        last_signals.append(signal_data)
        
        # Mantém apenas últimos 50 sinais
        if len(last_signals) > 50:
            last_signals.pop(0)
        
        return signal_text
        
    except Exception as e:
        logger.error(f"Erro ao gerar sinal para {symbol}: {e}")
    
    return None

# =========================
# SISTEMA DE MONITORAMENTO
# =========================
def check_signals():
    """Verifica sinais para todos os pares"""
    if signals_paused:
        return
    
    logger.info(f"Verificando {len(PAIRS)} pares...")
    
    signals_generated = 0
    for pair in PAIRS:
        try:
            df = get_binance_data(pair)
            if df is None or len(df) < 50:
                continue
            
            signal = generate_signal(df, pair)
            if signal:
                logger.info(f"✅ Sinal para {pair}")
                try:
                    bot.send_message(CHAT_ID, signal)
                    signals_generated += 1
                    time.sleep(0.5)  # Delay para não sobrecarregar
                except Exception as e:
                    logger.error(f"Erro Telegram {pair}: {e}")
                    
        except Exception as e:
            logger.error(f"Erro ao processar {pair}: {e}")
    
    if signals_generated > 0:
        logger.info(f"Total de sinais gerados: {signals_generated}")

# =========================
# DASHBOARD FLASK SIMPLIFICADO
# =========================
app = Flask(__name__)

@app.route('/')
def dashboard():
    """Dashboard principal"""
    # Estatísticas
    total_signals = len(last_signals)
    buy_signals = len([s for s in last_signals if s['direction'] == 'COMPRA'])
    sell_signals = total_signals - buy_signals
    
    # Sinais recentes
    recent_signals = last_signals[-10:] if len(last_signals) > 10 else last_signals
    
    # Estratégias ativas
    active_strategies = sum(1 for s in STRATEGIES.values() if s['active'])
    
    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Crypto Scalping Bot</title>
        <style>
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #1a2980, #26d0ce);
                color: #333;
                margin: 0;
                padding: 20px;
            }
            .container {
                max-width: 1200px;
                margin: 0 auto;
            }
            .header {
                background: white;
                border-radius: 15px;
                padding: 30px;
                margin-bottom: 25px;
                text-align: center;
                box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            }
            .stats {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 15px;
                margin-bottom: 25px;
            }
            .stat-card {
                background: white;
                border-radius: 10px;
                padding: 20px;
                text-align: center;
                box-shadow: 0 5px 15px rgba(0,0,0,0.08);
            }
            .stat-value {
                font-size: 2rem;
                font-weight: bold;
                margin: 10px 0;
            }
            .card {
                background: white;
                border-radius: 15px;
                padding: 25px;
                margin-bottom: 25px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.08);
            }
            .signal-row {
                padding: 15px;
                margin: 10px 0;
                border-radius: 8px;
                border-left: 4px solid;
            }
            .buy-signal {
                border-left-color: #27ae60;
                background: rgba(39, 174, 96, 0.05);
            }
            .sell-signal {
                border-left-color: #e74c3c;
                background: rgba(231, 76, 60, 0.05);
            }
            .btn {
                padding: 12px 25px;
                margin: 0 10px;
                background: #3498db;
                color: white;
                text-decoration: none;
                border-radius: 8px;
                font-weight: 600;
                border: none;
                cursor: pointer;
            }
            .btn-pause { background: #e74c3c; }
            .btn-resume { background: #27ae60; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🤖 Crypto Scalping Bot</h1>
                <p>Monitorando {{ pairs }} pares com {{ strategies }} estratégias</p>
                <div>
                    {% if not paused %}
                    <a href="/pause" class="btn btn-pause">⏸️ Pausar Bot</a>
                    {% else %}
                    <a href="/resume" class="btn btn-resume">▶️ Retomar Bot</a>
                    {% endif %}
                    <a href="/health" class="btn">❤️ Saúde</a>
                </div>
            </div>
            
            <div class="stats">
                <div class="stat-card">
                    <div>Pares Ativos</div>
                    <div class="stat-value">{{ pairs }}</div>
                </div>
                <div class="stat-card">
                    <div>Estratégias</div>
                    <div class="stat-value">{{ strategies }}</div>
                </div>
                <div class="stat-card">
                    <div>Sinais Totais</div>
                    <div class="stat-value">{{ total_signals }}</div>
                </div>
                <div class="stat-card">
                    <div>Buy/Sell</div>
                    <div class="stat-value">{{ buy_signals }}/{{ sell_signals }}</div>
                </div>
                <div class="stat-card">
                    <div>Uptime</div>
                    <div class="stat-value">{{ uptime }}</div>
                </div>
                <div class="stat-card">
                    <div>Status</div>
                    <div class="stat-value" style="color: {{ 'green' if not paused else 'red' }}">
                        {{ 'ATIVO' if not paused else 'PAUSADO' }}
                    </div>
                </div>
            </div>
            
            <div class="card">
                <h2>📋 Últimos Sinais</h2>
                {% if recent_signals %}
                    {% for signal in recent_signals|reverse %}
                    <div class="signal-row {{ 'buy-signal' if signal.direction == 'COMPRA' else 'sell-signal' }}">
                        <strong>{{ signal.time.strftime('%H:%M:%S') }}</strong> - 
                        {{ signal.symbol }} - 
                        <span style="color: {{ 'green' if signal.direction == 'COMPRA' else 'red' }}">
                            {{ signal.direction }}
                        </span> a ${{ format_price(signal.entry, signal.symbol) }}
                        <br><small>Confiança: {{ signal.confidence|round(1) }} | Estratégias: {{ signal.strategies_used }}</small>
                    </div>
                    {% endfor %}
                {% else %}
                    <p style="text-align: center; color: #666;">Nenhum sinal gerado ainda</p>
                {% endif %}
            </div>
            
            <div style="text-align: center; color: white; margin-top: 30px;">
                <p>🔄 Auto-atualização em 60s | 🚀 Render.com | 🐍 Python 3.10</p>
            </div>
        </div>
        
        <script>
            setTimeout(() => location.reload(), 60000);
        </script>
    </body>
    </html>
    '''
    
    return render_template_string(
        html,
        pairs=len(PAIRS),
        strategies=active_strategies,
        total_signals=total_signals,
        buy_signals=buy_signals,
        sell_signals=sell_signals,
        recent_signals=recent_signals,
        paused=signals_paused,
        uptime=get_uptime(),
        format_price=format_price
    )

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
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #1a2980, #26d0ce);
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
            }
            .message {
                background: white;
                padding: 40px;
                border-radius: 15px;
                text-align: center;
            }
        </style>
    </head>
    <body>
        <div class="message">
            <h1>⏸️ Bot Pausado</h1>
            <p>O bot foi pausado com sucesso.</p>
            <a href="/" style="display: inline-block; padding: 10px 20px; background: #3498db; color: white; text-decoration: none; border-radius: 8px; margin-top: 20px;">
                Voltar ao Dashboard
            </a>
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
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #1a2980, #26d0ce);
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
            }
            .message {
                background: white;
                padding: 40px;
                border-radius: 15px;
                text-align: center;
            }
        </style>
    </head>
    <body>
        <div class="message">
            <h1>▶️ Bot Retomado</h1>
            <p>O bot foi reativado com sucesso.</p>
            <a href="/" style="display: inline-block; padding: 10px 20px; background: #27ae60; color: white; text-decoration: none; border-radius: 8px; margin-top: 20px;">
                Voltar ao Dashboard
            </a>
        </div>
    </body>
    </html>
    '''

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'bot_running': not signals_paused,
        'pairs_monitored': len(PAIRS),
        'strategies_active': sum(1 for s in STRATEGIES.values() if s['active']),
        'signals_generated': len(last_signals),
        'uptime': get_uptime()
    })

# =========================
# FUNÇÕES PRINCIPAIS
# =========================
def run_flask():
    """Executa servidor Flask"""
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"🚀 Iniciando servidor na porta {port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

def run_signal_checker():
    """Executa verificação periódica de sinais"""
    logger.info("📊 Iniciando verificador de sinais...")
    
    # Verifica imediatamente ao iniciar
    check_signals()
    
    # Agenda verificações a cada 1 minuto
    schedule.every(1).minutes.do(check_signals)
    
    while True:
        schedule.run_pending()
        time.sleep(1)

def main():
    """Função principal"""
    logger.info("=" * 60)
    logger.info("🤖 CRYPTO SCALPING BOT INICIANDO")
    logger.info("=" * 60)
    logger.info(f"📊 Pares: {len(PAIRS)}")
    logger.info(f"🎯 Estratégias: {sum(1 for s in STRATEGIES.values() if s['active'])}")
    logger.info(f"🌐 Dashboard: http://localhost:10000")
    logger.info("=" * 60)
    
    # Envia mensagem de início
    try:
        startup_msg = (
            f"🚀 <b>CRYPTO BOT INICIADO</b>\n\n"
            f"📊 <b>Configuração:</b>\n"
            f"• Pares: {len(PAIRS)}\n"
            f"• Estratégias: {sum(1 for s in STRATEGIES.values() if s['active'])}\n"
            f"• Intervalo: 1 minuto\n\n"
            f"✅ Sistema operacional!"
        )
        bot.send_message(CHAT_ID, startup_msg)
    except Exception as e:
        logger.error(f"❌ Erro ao enviar mensagem inicial: {e}")
    
    # Inicia threads
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    signal_thread = threading.Thread(target=run_signal_checker, daemon=True)
    
    flask_thread.start()
    signal_thread.start()
    
    # Mantém thread principal ativa
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("👋 Bot encerrado pelo usuário")

if __name__ == "__main__":
    main()
