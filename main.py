import telebot
import requests
import pandas as pd
import time
import schedule
import threading
from flask import Flask, render_template_string
import os
from datetime import datetime, timedelta
import logging
from typing import Optional, List, Dict
import json

# =========================
# CONFIGURAÇÃO DE LOG
# =========================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_scalping.log'),
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
signal_cache = {}  # Cache para evitar sinais duplicados
bot_start_time = datetime.now()

# Configuração de pares
PAIRS = [
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT',
    'ADAUSDT', 'XRPUSDT', 'DOGEUSDT', 'LINKUSDT', 'AVAXUSDT'
]

# Configurações de estratégia
STRATEGIES = {
    'ema_vwap': {'weight': 1.0, 'active': True},
    'rsi_scalping': {'weight': 0.8, 'active': True},
    'macd': {'weight': 0.9, 'active': True}
}

# =========================
# FUNÇÕES UTILITÁRIAS
# =========================
def format_price(price: float, symbol: str) -> str:
    """Formata preço baseado no par"""
    if 'BTC' in symbol or 'ETH' in symbol:
        return f"{price:.2f}"
    return f"{price:.4f}"

def get_uptime() -> str:
    """Calcula tempo de atividade do bot"""
    uptime = datetime.now() - bot_start_time
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    return f"{hours}h {minutes}m {seconds}s"

# =========================
# BINANCE DATA - COM TRATAMENTO DE ERROS
# =========================
def get_binance_data(symbol: str, interval: str = '1m', limit: int = 300) -> Optional[pd.DataFrame]:
    """Obtém dados da Binance com tratamento robusto de erros"""
    try:
        url = 'https://api.binance.com/api/v3/klines'
        params = {'symbol': symbol, 'interval': interval, 'limit': limit}
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        if not data:
            logger.warning(f"Nenhum dado retornado para {symbol}")
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
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Erro na requisição para {symbol}: {e}")
        return None
    except Exception as e:
        logger.error(f"Erro ao processar dados de {symbol}: {e}")
        return None

# =========================
# INDICADORES OTIMIZADOS
# =========================
def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calcula RSI de forma mais eficiente"""
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_macd(df: pd.DataFrame) -> tuple:
    """Calcula MACD e Signal line"""
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    macd_line = exp1 - exp2
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    return macd_line, signal_line

# =========================
# ESTRATÉGIAS COM PESOS
# =========================
def ema_vwap_strategy(df: pd.DataFrame) -> Optional[str]:
    """Estratégia EMA + VWAP"""
    try:
        df['EMA9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['EMA21'] = df['close'].ewm(span=21, adjust=False).mean()
        
        tp = (df['high'] + df['low'] + df['close']) / 3
        df['VWAP'] = (tp * df['volume']).cumsum() / df['volume'].cumsum()
        
        last, prev = df.iloc[-1], df.iloc[-2]
        
        # Condições de compra
        buy_conditions = (
            last['close'] > last['VWAP'] and
            last['EMA9'] > last['EMA21'] and
            prev['EMA9'] <= prev['EMA21']
        )
        
        # Condições de venda
        sell_conditions = (
            last['close'] < last['VWAP'] and
            last['EMA9'] < last['EMA21'] and
            prev['EMA9'] >= prev['EMA21']
        )
        
        return 'buy' if buy_conditions else 'sell' if sell_conditions else None
        
    except Exception as e:
        logger.error(f"Erro em EMA_VWAP: {e}")
        return None

def rsi_scalping_strategy(df: pd.DataFrame) -> Optional[str]:
    """Estratégia RSI para scalping"""
    try:
        df['RSI'] = calculate_rsi(df)
        r = df['RSI'].iloc[-1]
        
        if 30 < r < 45:
            return 'buy'
        elif 55 < r < 70:
            return 'sell'
        return None
    except Exception as e:
        logger.error(f"Erro em RSI Scalping: {e}")
        return None

def macd_strategy(df: pd.DataFrame) -> Optional[str]:
    """Estratégia MACD"""
    try:
        macd_line, signal_line = calculate_macd(df)
        df['MACD'] = macd_line
        df['SIGNAL'] = signal_line
        
        last, prev = df.iloc[-1], df.iloc[-2]
        
        if prev['MACD'] < prev['SIGNAL'] and last['MACD'] > last['SIGNAL']:
            return 'buy'
        if prev['MACD'] > prev['SIGNAL'] and last['MACD'] < last['SIGNAL']:
            return 'sell'
        return None
    except Exception as e:
        logger.error(f"Erro em MACD: {e}")
        return None

def volume_filter(df: pd.DataFrame, window: int = 20) -> bool:
    """Filtro de volume"""
    try:
        current_volume = df['volume'].iloc[-1]
        avg_volume = df['volume'].rolling(window=window).mean().iloc[-1]
        return current_volume > avg_volume * 1.2  # Volume 20% acima da média
    except:
        return False

# =========================
# GERAÇÃO DE SINAL COM CACHE
# =========================
def is_signal_duplicate(symbol: str, direction: str) -> bool:
    """Verifica se sinal é duplicado recentemente"""
    cache_key = f"{symbol}_{direction}"
    current_time = datetime.now()
    
    if cache_key in signal_cache:
        last_time = signal_cache[cache_key]
        if current_time - last_time < timedelta(minutes=5):
            return True
    
    # Limpa cache antigo
    keys_to_delete = []
    for key, timestamp in signal_cache.items():
        if current_time - timestamp > timedelta(minutes=10):
            keys_to_delete.append(key)
    
    for key in keys_to_delete:
        del signal_cache[key]
    
    signal_cache[cache_key] = current_time
    return False

def generate_signal(df: pd.DataFrame, symbol: str) -> Optional[str]:
    """Gera sinal baseado em múltiplas estratégias"""
    try:
        if not volume_filter(df):
            return None
        
        # Executa estratégias ativas
        signals = {}
        if STRATEGIES['ema_vwap']['active']:
            signals['ema_vwap'] = ema_vwap_strategy(df)
        if STRATEGIES['rsi_scalping']['active']:
            signals['rsi_scalping'] = rsi_scalping_strategy(df)
        if STRATEGIES['macd']['active']:
            signals['macd'] = macd_strategy(df)
        
        # Contagem ponderada
        buy_score = 0
        sell_score = 0
        
        for strategy, result in signals.items():
            if result:
                weight = STRATEGIES[strategy]['weight']
                if result == 'buy':
                    buy_score += weight
                elif result == 'sell':
                    sell_score += weight
        
        # Determina direção (mínimo 2 estratégias concordando)
        threshold = 1.5
        if buy_score >= threshold or sell_score >= threshold:
            if buy_score > sell_score and not is_signal_duplicate(symbol, 'buy'):
                direction = 'COMPRA'
                emoji = '🚀'
                tp_mult = 1.003
                sl_mult = 0.998
                confidence = buy_score
            elif sell_score > buy_score and not is_signal_duplicate(symbol, 'sell'):
                direction = 'VENDA'
                emoji = '🔻'
                tp_mult = 0.997
                sl_mult = 1.002
                confidence = sell_score
            else:
                return None
            
            entry = df['close'].iloc[-1]
            tp = entry * tp_mult
            sl = entry * sl_mult
            
            # Formata o preço baseado no símbolo
            formatted_entry = format_price(entry, symbol)
            formatted_tp = format_price(tp, symbol)
            formatted_sl = format_price(sl, symbol)
            
            signal_text = (
                f"{emoji} <b>SCALPING {direction}</b>\n"
                f"📊 Par: <code>{symbol}</code>\n"
                f"💰 Entrada: <b>{formatted_entry}</b>\n"
                f"🎯 TP: {formatted_tp} (+0.3%)\n"
                f"🛡️ SL: {formatted_sl} (-0.2%)\n"
                f"⏰ TF: 1m | 📈 Volume: Ativo\n"
                f"🕐 Hora: {datetime.now().strftime('%H:%M:%S')}\n"
                f"✅ Confiança: {confidence:.1f}/3.0"
            )
            
            # Armazena último sinal
            signal_data = {
                'time': datetime.now(),
                'symbol': symbol,
                'direction': direction,
                'entry': entry,
                'tp': tp,
                'sl': sl,
                'confidence': confidence,
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
# LOOP PRINCIPAL COM VALIDAÇÃO
# =========================
def check_signals():
    """Verifica sinais para todos os pares"""
    if signals_paused:
        return
    
    logger.info(f"Verificando sinais para {len(PAIRS)} pares...")
    
    for pair in PAIRS:
        try:
            df = get_binance_data(pair)
            if df is None or len(df) < 50:
                logger.warning(f"Dados insuficientes para {pair}")
                continue
            
            signal = generate_signal(df, pair)
            if signal:
                logger.info(f"✅ Sinal encontrado para {pair}")
                try:
                    bot.send_message(CHAT_ID, signal)
                    time.sleep(0.5)  # Delay entre mensagens
                except Exception as e:
                    logger.error(f"Erro ao enviar mensagem Telegram: {e}")
                    
        except Exception as e:
            logger.error(f"Erro ao processar {pair}: {e}")

# =========================
# COMANDOS TELEGRAM
# =========================
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """Comandos do bot no Telegram"""
    welcome_text = (
        "🤖 <b>Bot de Scalping Cripto - Dashboard</b>\n\n"
        "<b>Comandos disponíveis:</b>\n"
        "📊 /status - Status do sistema\n"
        "⏸️ /pause - Pausar sinais\n"
        "▶️ /resume - Retomar sinais\n"
        "📈 /pairs - Pares monitorados\n"
        "📋 /signals - Últimos sinais\n"
        "⚙️ /settings - Configurações\n"
        "ℹ️ /info - Informações do bot\n\n"
        "🌐 Dashboard web disponível!"
    )
    bot.reply_to(message, welcome_text)

@bot.message_handler(commands=['status'])
def send_status(message):
    """Status do bot"""
    status_emoji = "⏸️" if signals_paused else "🟢"
    status_text = "PAUSADO" if signals_paused else "ATIVO"
    uptime = get_uptime()
    
    active_strategies = sum(1 for s in STRATEGIES.values() if s['active'])
    
    status_message = (
        f"{status_emoji} <b>STATUS DO SISTEMA</b>\n\n"
        f"📊 Status: {status_text}\n"
        f"⏱️ Uptime: {uptime}\n"
        f"📈 Pares: {len(PAIRS)}\n"
        f"⚡ Estratégias ativas: {active_strategies}/3\n"
        f"📋 Sinais hoje: {len(last_signals)}\n"
        f"🔄 Próxima verificação: {datetime.now().strftime('%H:%M:%S')}"
    )
    bot.reply_to(message, status_message)

@bot.message_handler(commands=['pause'])
def pause_signals(message):
    """Pausa sinais"""
    global signals_paused
    signals_paused = True
    bot.reply_to(message, "⏸️ <b>Sinais pausados</b>\nO bot parou de gerar novos sinais.")

@bot.message_handler(commands=['resume'])
def resume_signals(message):
    """Retoma sinais"""
    global signals_paused
    signals_paused = False
    bot.reply_to(message, "▶️ <b>Sinais retomados</b>\nO bot voltou a gerar sinais.")

@bot.message_handler(commands=['pairs'])
def list_pairs(message):
    """Lista pares monitorados"""
    pairs_list = "\n".join([f"• {pair}" for pair in PAIRS])
    response = (
        f"📊 <b>PARES MONITORADOS</b>\n\n"
        f"Total: {len(PAIRS)} pares\n\n"
        f"{pairs_list}\n\n"
        f"Intervalo: 1 minuto\n"
        f"Exchange: Binance"
    )
    bot.reply_to(message, response)

@bot.message_handler(commands=['signals'])
def list_signals(message):
    """Lista últimos sinais"""
    if not last_signals:
        bot.reply_to(message, "📭 <b>Nenhum sinal gerado ainda</b>")
        return
    
    recent_signals = last_signals[-5:]  # Últimos 5 sinais
    
    signals_text = ""
    for signal in reversed(recent_signals):
        emoji = "🟢" if signal['direction'] == 'COMPRA' else "🔴"
        signals_text += f"{emoji} {signal['symbol']} - {signal['direction']} a {format_price(signal['entry'], signal['symbol'])}\n"
    
    response = (
        f"📋 <b>ÚLTIMOS SINAIS</b>\n\n"
        f"{signals_text}\n"
        f"Total de sinais: {len(last_signals)}"
    )
    bot.reply_to(message, response)

@bot.message_handler(commands=['info'])
def bot_info(message):
    """Informações do bot"""
    info_text = (
        "🤖 <b>CRYPTO SCALPING BOT</b>\n\n"
        "<b>Desenvolvimento:</b>\n"
        "• Estratégias múltiplas\n"
        "• Filtro de volume\n"
        "• Sistema de confiança\n"
        "• Proteção contra duplicados\n\n"
        "<b>Características:</b>\n"
        "• Intervalo: 1 minuto\n"
        "• Alvo: 0.3%\n"
        "• Stop: 0.2%\n"
        "• Dashboard web integrado\n\n"
        "⚠️ <i>Aviso: Este é um bot para sinais educacionais.</i>"
    )
    bot.reply_to(message, info_text)

# =========================
# DASHBOARD FLASK PROFISSIONAL
# =========================
app = Flask(__name__)

@app.route('/')
def dashboard():
    """Dashboard profissional com métricas em tempo real"""
    
    # Calcula métricas para exibição
    total_signals = len(last_signals)
    buy_signals = len([s for s in last_signals if s['direction'] == 'COMPRA'])
    sell_signals = total_signals - buy_signals
    
    # Sinais de hoje
    today = datetime.now().date()
    today_signals = [s for s in last_signals if s['time'].date() == today]
    
    # Últimos sinais
    recent_signals = last_signals[-10:] if len(last_signals) > 10 else last_signals
    
    # Estratégias ativas
    active_strategies = sum(1 for s in STRATEGIES.values() if s['active'])
    
    # Tempo de atividade
    uptime = get_uptime()
    
    html_template = """
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Crypto Scalping Bot - Dashboard</title>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            :root {
                --primary: #2c3e50;
                --secondary: #3498db;
                --success: #27ae60;
                --danger: #e74c3c;
                --warning: #f39c12;
                --light: #ecf0f1;
                --dark: #2c3e50;
                --gray: #95a5a6;
            }
            
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #1a2980, #26d0ce);
                color: #333;
                min-height: 100vh;
            }
            
            .dashboard {
                max-width: 1400px;
                margin: 0 auto;
                padding: 20px;
            }
            
            .header {
                background: rgba(255, 255, 255, 0.95);
                border-radius: 15px;
                padding: 25px;
                margin-bottom: 25px;
                box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
                display: flex;
                justify-content: space-between;
                align-items: center;
                flex-wrap: wrap;
            }
            
            .logo {
                display: flex;
                align-items: center;
                gap: 15px;
            }
            
            .logo-icon {
                font-size: 2.5rem;
                color: var(--secondary);
            }
            
            .logo-text h1 {
                font-size: 1.8rem;
                color: var(--primary);
                margin-bottom: 5px;
            }
            
            .logo-text p {
                color: var(--gray);
                font-size: 0.9rem;
            }
            
            .status-badge {
                display: inline-block;
                padding: 8px 20px;
                border-radius: 50px;
                font-weight: 600;
                font-size: 0.9rem;
            }
            
            .status-active {
                background: var(--success);
                color: white;
            }
            
            .status-paused {
                background: var(--danger);
                color: white;
            }
            
            .controls {
                display: flex;
                gap: 10px;
            }
            
            .btn {
                padding: 10px 20px;
                border: none;
                border-radius: 8px;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.3s ease;
                display: flex;
                align-items: center;
                gap: 8px;
                text-decoration: none;
            }
            
            .btn-pause {
                background: var(--danger);
                color: white;
            }
            
            .btn-resume {
                background: var(--success);
                color: white;
            }
            
            .btn:hover {
                transform: translateY(-2px);
                box-shadow: 0 5px 15px rgba(0, 0, 0, 0.2);
            }
            
            .metrics-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
                gap: 20px;
                margin-bottom: 25px;
            }
            
            .metric-card {
                background: rgba(255, 255, 255, 0.95);
                border-radius: 12px;
                padding: 20px;
                box-shadow: 0 5px 15px rgba(0, 0, 0, 0.08);
                transition: transform 0.3s ease;
            }
            
            .metric-card:hover {
                transform: translateY(-5px);
            }
            
            .metric-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 15px;
            }
            
            .metric-icon {
                font-size: 1.8rem;
                padding: 12px;
                border-radius: 10px;
            }
            
            .icon-blue { background: #e3f2fd; color: var(--secondary); }
            .icon-green { background: #e8f5e9; color: var(--success); }
            .icon-red { background: #ffebee; color: var(--danger); }
            .icon-orange { background: #fff3e0; color: var(--warning); }
            
            .metric-value {
                font-size: 2.2rem;
                font-weight: 700;
                margin-bottom: 5px;
            }
            
            .metric-label {
                color: var(--gray);
                font-size: 0.9rem;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            
            .main-content {
                display: grid;
                grid-template-columns: 2fr 1fr;
                gap: 25px;
            }
            
            .signals-card, .pairs-card {
                background: rgba(255, 255, 255, 0.95);
                border-radius: 15px;
                padding: 25px;
                box-shadow: 0 5px 15px rgba(0, 0, 0, 0.08);
            }
            
            .card-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 20px;
                padding-bottom: 15px;
                border-bottom: 2px solid var(--light);
            }
            
            .card-title {
                font-size: 1.4rem;
                color: var(--primary);
                display: flex;
                align-items: center;
                gap: 10px;
            }
            
            .card-title i {
                color: var(--secondary);
            }
            
            .signals-table {
                width: 100%;
                border-collapse: collapse;
            }
            
            .signals-table th {
                text-align: left;
                padding: 12px 15px;
                background: var(--light);
                color: var(--dark);
                font-weight: 600;
                border-bottom: 2px solid var(--gray);
            }
            
            .signals-table td {
                padding: 15px;
                border-bottom: 1px solid #eee;
            }
            
            .signal-buy {
                border-left: 4px solid var(--success);
            }
            
            .signal-sell {
                border-left: 4px solid var(--danger);
            }
            
            .signal-direction {
                display: inline-block;
                padding: 5px 12px;
                border-radius: 20px;
                font-weight: 600;
                font-size: 0.8rem;
            }
            
            .direction-buy {
                background: rgba(39, 174, 96, 0.1);
                color: var(--success);
            }
            
            .direction-sell {
                background: rgba(231, 76, 60, 0.1);
                color: var(--danger);
            }
            
            .signal-price {
                font-weight: 700;
                font-size: 1.1rem;
            }
            
            .pairs-list {
                display: flex;
                flex-wrap: wrap;
                gap: 10px;
                margin-top: 15px;
            }
            
            .pair-badge {
                background: var(--light);
                padding: 8px 15px;
                border-radius: 20px;
                font-weight: 600;
                font-size: 0.85rem;
                display: flex;
                align-items: center;
                gap: 5px;
            }
            
            .pair-badge i {
                color: var(--secondary);
            }
            
            .empty-state {
                text-align: center;
                padding: 40px 20px;
                color: var(--gray);
            }
            
            .empty-state i {
                font-size: 3rem;
                margin-bottom: 15px;
                color: var(--light);
            }
            
            .last-update {
                text-align: center;
                margin-top: 30px;
                color: white;
                font-size: 0.85rem;
                opacity: 0.8;
            }
            
            .strategy-status {
                display: flex;
                align-items: center;
                gap: 8px;
                margin: 5px 0;
            }
            
            .strategy-dot {
                width: 10px;
                height: 10px;
                border-radius: 50%;
            }
            
            .strategy-active {
                background: var(--success);
            }
            
            .strategy-inactive {
                background: var(--gray);
            }
            
            @media (max-width: 1024px) {
                .main-content {
                    grid-template-columns: 1fr;
                }
            }
            
            @media (max-width: 768px) {
                .header {
                    flex-direction: column;
                    gap: 20px;
                    text-align: center;
                }
                
                .logo {
                    flex-direction: column;
                }
                
                .metrics-grid {
                    grid-template-columns: 1fr;
                }
                
                .signals-table {
                    display: block;
                    overflow-x: auto;
                }
            }
        </style>
    </head>
    <body>
        <div class="dashboard">
            <!-- Header -->
            <div class="header">
                <div class="logo">
                    <div class="logo-icon">
                        <i class="fas fa-robot"></i>
                    </div>
                    <div class="logo-text">
                        <h1>Crypto Scalping Bot</h1>
                        <p>Sistema automatizado de trading para criptomoedas</p>
                    </div>
                </div>
                <div class="status">
                    <span class="status-badge {{ 'status-active' if not paused else 'status-paused' }}">
                        <i class="fas fa-{{ 'play' if not paused else 'pause' }}"></i>
                        {{ 'ATIVO' if not paused else 'PAUSADO' }}
                    </span>
                </div>
                <div class="controls">
                    {% if not paused %}
                    <a href="/pause" class="btn btn-pause">
                        <i class="fas fa-pause"></i>
                        Pausar Bot
                    </a>
                    {% else %}
                    <a href="/resume" class="btn btn-resume">
                        <i class="fas fa-play"></i>
                        Retomar Bot
                    </a>
                    {% endif %}
                    <a href="/stats" class="btn" style="background: var(--secondary); color: white;">
                        <i class="fas fa-chart-bar"></i>
                        Estatísticas
                    </a>
                </div>
            </div>
            
            <!-- Metrics Grid -->
            <div class="metrics-grid">
                <div class="metric-card">
                    <div class="metric-header">
                        <div>
                            <div class="metric-value">{{ pairs_count }}</div>
                            <div class="metric-label">Pares Monitorados</div>
                        </div>
                        <div class="metric-icon icon-blue">
                            <i class="fas fa-chart-line"></i>
                        </div>
                    </div>
                    <p>Ativos sendo analisados em tempo real</p>
                </div>
                
                <div class="metric-card">
                    <div class="metric-header">
                        <div>
                            <div class="metric-value">{{ total_signals }}</div>
                            <div class="metric-label">Total de Sinais</div>
                        </div>
                        <div class="metric-icon icon-green">
                            <i class="fas fa-bell"></i>
                        </div>
                    </div>
                    <p>Sinais gerados desde o início</p>
                </div>
                
                <div class="metric-card">
                    <div class="metric-header">
                        <div>
                            <div class="metric-value">{{ buy_signals }}</div>
                            <div class="metric-label">Sinais de Compra</div>
                        </div>
                        <div class="metric-icon icon-green">
                            <i class="fas fa-arrow-up"></i>
                        </div>
                    </div>
                    <p>Oportunidades de entrada long identificadas</p>
                </div>
                
                <div class="metric-card">
                    <div class="metric-header">
                        <div>
                            <div class="metric-value">{{ sell_signals }}</div>
                            <div class="metric-label">Sinais de Venda</div>
                        </div>
                        <div class="metric-icon icon-red">
                            <i class="fas fa-arrow-down"></i>
                        </div>
                    </div>
                    <p>Oportunidades de entrada short identificadas</p>
                </div>
            </div>
            
            <!-- Main Content -->
            <div class="main-content">
                <!-- Signals Table -->
                <div class="signals-card">
                    <div class="card-header">
                        <h2 class="card-title">
                            <i class="fas fa-history"></i>
                            Últimos Sinais
                        </h2>
                        <span class="metric-label">{{ recent_signals|length }} registros</span>
                    </div>
                    
                    {% if recent_signals %}
                    <table class="signals-table">
                        <thead>
                            <tr>
                                <th>Horário</th>
                                <th>Par</th>
                                <th>Direção</th>
                                <th>Entrada</th>
                                <th>Confiança</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for signal in recent_signals|reverse %}
                            <tr class="{{ 'signal-buy' if signal.direction == 'COMPRA' else 'signal-sell' }}">
                                <td>
                                    <strong>{{ signal.time.strftime('%H:%M:%S') }}</strong><br>
                                    <small>{{ signal.time.strftime('%d/%m') }}</small>
                                </td>
                                <td>
                                    <strong>{{ signal.symbol }}</strong><br>
                                    <small>Binance</small>
                                </td>
                                <td>
                                    <span class="signal-direction {{ 'direction-buy' if signal.direction == 'COMPRA' else 'direction-sell' }}">
                                        <i class="fas fa-{{ 'arrow-up' if signal.direction == 'COMPRA' else 'arrow-down' }}"></i>
                                        {{ signal.direction }}
                                    </span>
                                </td>
                                <td>
                                    <span class="signal-price">
                                        ${{ format_price(signal.entry, signal.symbol) }}
                                    </span>
                                </td>
                                <td>
                                    <div style="display: flex; align-items: center; gap: 5px;">
                                        <div style="
                                            width: {{ signal.confidence * 20 }}px;
                                            height: 10px;
                                            background: {{ 'var(--success)' if signal.confidence >= 2 else 'var(--warning)' }};
                                            border-radius: 5px;
                                        "></div>
                                        <span>{{ "%.1f"|format(signal.confidence) }}</span>
                                    </div>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                    {% else %}
                    <div class="empty-state">
                        <i class="fas fa-inbox"></i>
                        <h3>Nenhum sinal gerado ainda</h3>
                        <p>Os sinais aparecerão aqui quando o bot identificar oportunidades de trading</p>
                    </div>
                    {% endif %}
                </div>
                
                <!-- Pairs and Info -->
                <div class="pairs-card">
                    <div class="card-header">
                        <h2 class="card-title">
                            <i class="fas fa-coins"></i>
                            Informações do Sistema
                        </h2>
                    </div>
                    
                    <div style="margin-bottom: 20px;">
                        <h3 style="margin-bottom: 10px; color: var(--primary);">
                            <i class="fas fa-cogs"></i>
                            Configurações
                        </h3>
                        <div class="strategy-status">
                            <div class="strategy-dot {{ 'strategy-active' if strategies_active.ema_vwap else 'strategy-inactive' }}"></div>
                            <span>EMA+VWAP: {{ 'Ativa' if strategies_active.ema_vwap else 'Inativa' }}</span>
                        </div>
                        <div class="strategy-status">
                            <div class="strategy-dot {{ 'strategy-active' if strategies_active.rsi_scalping else 'strategy-inactive' }}"></div>
                            <span>RSI Scalping: {{ 'Ativa' if strategies_active.rsi_scalping else 'Inativa' }}</span>
                        </div>
                        <div class="strategy-status">
                            <div class="strategy-dot {{ 'strategy-active' if strategies_active.macd else 'strategy-inactive' }}"></div>
                            <span>MACD: {{ 'Ativa' if strategies_active.macd else 'Inativa' }}</span>
                        </div>
                    </div>
                    
                    <div style="margin-bottom: 20px;">
                        <h3 style="margin-bottom: 10px; color: var(--primary);">
                            <i class="fas fa-exchange-alt"></i>
                            Pares Ativos
                        </h3>
                        <div class="pairs-list">
                            {% for pair in pairs %}
                            <div class="pair-badge">
                                {% if 'BTC' in pair %}
                                <i class="fab fa-btc"></i>
                                {% elif 'ETH' in pair %}
                                <i class="fab fa-ethereum"></i>
                                {% else %}
                                <i class="fas fa-coins"></i>
                                {% endif %}
                                {{ pair }}
                            </div>
                            {% endfor %}
                        </div>
                    </div>
                    
                    <div style="padding-top: 20px; border-top: 2px solid var(--light);">
                        <h3 style="margin-bottom: 10px; color: var(--primary);">
                            <i class="fas fa-info-circle"></i>
                            Estatísticas
                        </h3>
                        <ul style="list-style: none; padding: 0;">
                            <li style="margin-bottom: 8px; display: flex; justify-content: space-between;">
                                <span>Tempo de atividade:</span>
                                <strong>{{ uptime }}</strong>
                            </li>
                            <li style="margin-bottom: 8px; display: flex; justify-content: space-between;">
                                <span>Sinais hoje:</span>
                                <strong>{{ today_signals|length }}</strong>
                            </li>
                            <li style="margin-bottom: 8px; display: flex; justify-content: space-between;">
                                <span>Taxa de sucesso:</span>
                                <strong>{{ "%.1f"|format(success_rate) }}%</strong>
                            </li>
                            <li style="margin-bottom: 8px; display: flex; justify-content: space-between;">
                                <span>Última verificação:</span>
                                <strong>{{ current_time.strftime('%H:%M:%S') }}</strong>
                            </li>
                        </ul>
                    </div>
                </div>
            </div>
            
            <!-- Footer -->
            <div class="last-update">
                <p>
                    <i class="fas fa-sync-alt"></i>
                    Atualização automática em 60s | 
                    <i class="fas fa-shield-alt"></i>
                    Sistema operacional desde {{ bot_start_time.strftime('%d/%m/%Y %H:%M') }}
                </p>
            </div>
        </div>
        
        <!-- Auto-refresh script -->
        <script>
            // Auto-refresh a cada 60 segundos
            setTimeout(function() {
                location.reload();
            }, 60000);
            
            // Adiciona confirmação para pausar/retomar
            document.querySelectorAll('.btn').forEach(button => {
                if (button.href && button.href.includes('/pause')) {
                    button.addEventListener('click', function(e) {
                        if (!confirm('Tem certeza que deseja pausar o bot?')) {
                            e.preventDefault();
                        }
                    });
                }
                
                if (button.href && button.href.includes('/resume')) {
                    button.addEventListener('click', function(e) {
                        if (!confirm('Tem certeza que deseja retomar o bot?')) {
                            e.preventDefault();
                        }
                    });
                }
            });
            
            // Efeito de realce para novos sinais
            function highlightNewRows() {
                const rows = document.querySelectorAll('.signals-table tbody tr');
                if (rows.length > 0) {
                    rows[0].style.animation = 'highlight 2s';
                }
            }
            
            // Adiciona estilo para highlight
            const style = document.createElement('style');
            style.textContent = `
                @keyframes highlight {
                    0% { background-color: rgba(52, 152, 219, 0.3); }
                    100% { background-color: transparent; }
                }
            `;
            document.head.appendChild(style);
            
            // Executa quando a página carrega
            document.addEventListener('DOMContentLoaded', highlightNewRows);
            
            // Notificação de novo sinal (simulada)
            function checkForNewSignals() {
                fetch('/api/signals/count')
                    .then(response => response.json())
                    .then(data => {
                        if (data.count > {{ recent_signals|length }}) {
                            showNotification('Novo sinal detectado!');
                        }
                    });
            }
            
            function showNotification(message) {
                if (Notification.permission === 'granted') {
                    new Notification(message);
                }
            }
            
            // Solicita permissão para notificações
            if (Notification.permission === 'default') {
                Notification.requestPermission();
            }
            
            // Verifica novos sinais a cada 30 segundos
            setInterval(checkForNewSignals, 30000);
        </script>
    </body>
    </html>
    """
    
    current_time = datetime.now()
    
    # Calcula taxa de sucesso (simulada para exemplo)
    success_rate = 0.0
    if total_signals > 0:
        success_rate = (buy_signals / total_signals) * 100
    
    # Status das estratégias
    strategies_active = {
        'ema_vwap': STRATEGIES['ema_vwap']['active'],
        'rsi_scalping': STRATEGIES['rsi_scalping']['active'],
        'macd': STRATEGIES['macd']['active']
    }
    
    return render_template_string(
        html_template,
        recent_signals=recent_signals,
        total_signals=total_signals,
        buy_signals=buy_signals,
        sell_signals=sell_signals,
        today_signals=today_signals,
        pairs=PAIRS,
        pairs_count=len(PAIRS),
        paused=signals_paused,
        current_time=current_time,
        bot_start_time=bot_start_time,
        uptime=get_uptime(),
        success_rate=success_rate,
        strategies_active=strategies_active,
        format_price=format_price
    )

@app.route('/pause')
def pause_web():
    """Pausa o bot via web"""
    global signals_paused
    signals_paused = True
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Bot Pausado</title>
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
            .message-box {
                background: white;
                padding: 40px;
                border-radius: 15px;
                text-align: center;
                box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            }
            .icon {
                font-size: 4rem;
                color: #e74c3c;
                margin-bottom: 20px;
            }
            h1 {
                color: #2c3e50;
                margin-bottom: 10px;
            }
            p {
                color: #7f8c8d;
                margin-bottom: 30px;
            }
            .btn {
                display: inline-block;
                padding: 12px 30px;
                background: #3498db;
                color: white;
                text-decoration: none;
                border-radius: 8px;
                font-weight: 600;
                transition: all 0.3s;
            }
            .btn:hover {
                background: #2980b9;
                transform: translateY(-2px);
            }
        </style>
    </head>
    <body>
        <div class="message-box">
            <div class="icon">
                <i class="fas fa-pause-circle"></i>
            </div>
            <h1>Bot Pausado</h1>
            <p>O sistema de geração de sinais foi pausado com sucesso.</p>
            <a href="/" class="btn">Voltar ao Dashboard</a>
        </div>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/js/all.min.js"></script>
    </body>
    </html>
    """

@app.route('/resume')
def resume_web():
    """Retoma o bot via web"""
    global signals_paused
    signals_paused = False
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Bot Retomado</title>
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
            .message-box {
                background: white;
                padding: 40px;
                border-radius: 15px;
                text-align: center;
                box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            }
            .icon {
                font-size: 4rem;
                color: #27ae60;
                margin-bottom: 20px;
            }
            h1 {
                color: #2c3e50;
                margin-bottom: 10px;
            }
            p {
                color: #7f8c8d;
                margin-bottom: 30px;
            }
            .btn {
                display: inline-block;
                padding: 12px 30px;
                background: #3498db;
                color: white;
                text-decoration: none;
                border-radius: 8px;
                font-weight: 600;
                transition: all 0.3s;
            }
            .btn:hover {
                background: #2980b9;
                transform: translateY(-2px);
            }
        </style>
    </head>
    <body>
        <div class="message-box">
            <div class="icon">
                <i class="fas fa-play-circle"></i>
            </div>
            <h1>Bot Retomado</h1>
            <p>O sistema de geração de sinais foi reativado com sucesso.</p>
            <a href="/" class="btn">Voltar ao Dashboard</a>
        </div>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/js/all.min.js"></script>
    </body>
    </html>
    """

@app.route('/stats')
def statistics():
    """Página de estatísticas detalhadas"""
    stats_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Estatísticas - Crypto Scalping Bot</title>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #1a2980, #26d0ce);
                color: white;
                margin: 0;
                padding: 20px;
            }
            .container {
                max-width: 1200px;
                margin: 0 auto;
            }
            .back-btn {
                display: inline-block;
                margin-bottom: 20px;
                padding: 10px 20px;
                background: white;
                color: #3498db;
                text-decoration: none;
                border-radius: 8px;
                font-weight: 600;
            }
            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 20px;
                margin-top: 20px;
            }
            .stat-card {
                background: rgba(255, 255, 255, 0.1);
                padding: 20px;
                border-radius: 10px;
                backdrop-filter: blur(10px);
            }
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-btn">
                <i class="fas fa-arrow-left"></i> Voltar ao Dashboard
            </a>
            <h1><i class="fas fa-chart-bar"></i> Estatísticas Detalhadas</h1>
            <div class="stats-grid">
                <div class="stat-card">
                    <h3><i class="fas fa-robot"></i> Status do Bot</h3>
                    <p>Uptime: {{ uptime }}</p>
                    <p>Iniciado em: {{ bot_start_time.strftime('%d/%m/%Y %H:%M:%S') }}</p>
                </div>
                <div class="stat-card">
                    <h3><i class="fas fa-signal"></i> Sinais</h3>
                    <p>Total: {{ total_signals }}</p>
                    <p>Compras: {{ buy_signals }}</p>
                    <p>Vendas: {{ sell_signals }}</p>
                </div>
                <div class="stat-card">
                    <h3><i class="fas fa-cogs"></i> Configurações</h3>
                    <p>Pares: {{ pairs_count }}</p>
                    <p>Estratégias ativas: {{ active_strategies }}/3</p>
                    <p>Intervalo: 1 minuto</p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    
    active_strategies = sum(1 for s in STRATEGIES.values() if s['active'])
    
    return render_template_string(
        stats_html,
        uptime=get_uptime(),
        bot_start_time=bot_start_time,
        total_signals=len(last_signals),
        buy_signals=len([s for s in last_signals if s['direction'] == 'COMPRA']),
        sell_signals=len([s for s in last_signals if s['direction'] == 'VENDA']),
        pairs_count=len(PAIRS),
        active_strategies=active_strategies
    )

# =========================
# THREADS E EXECUÇÃO
# =========================
def run_flask():
    """Executa servidor Flask em thread separada"""
    logger.info(f"Iniciando servidor Flask na porta 8080...")
    app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)

def run_telegram_bot():
    """Executa polling do Telegram em thread separada"""
    logger.info("Iniciando bot do Telegram...")
    try:
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except Exception as e:
        logger.error(f"Erro no bot Telegram: {e}")

def run_signal_checker():
    """Executa verificação de sinais periódica"""
    logger.info("Iniciando verificador de sinais...")
    
    # Primeira execução imediata
    check_signals()
    
    # Agenda verificação a cada 1 minuto
    schedule.every(1).minutes.do(check_signals)
    
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except Exception as e:
            logger.error(f"Erro no verificador de sinais: {e}")
            time.sleep(5)

def main():
    """Função principal para iniciar o sistema"""
    logger.info("=" * 50)
    logger.info("INICIANDO CRYPTO SCALPING BOT")
    logger.info("=" * 50)
    logger.info(f"Pares monitorados: {len(PAIRS)}")
    logger.info(f"Estratégias ativas: {sum(1 for s in STRATEGIES.values() if s['active'])}")
    logger.info(f"Dashboard: http://localhost:8080")
    logger.info("=" * 50)
    
    try:
        # Envia mensagem de início para o Telegram
        startup_msg = (
            "🤖 <b>CRYPTO SCALPING BOT INICIADO</b>\n\n"
            f"⏱️ Hora: {datetime.now().strftime('%H:%M:%S')}\n"
            f"📊 Pares: {len(PAIRS)}\n"
            f"⚡ Estratégias: {sum(1 for s in STRATEGIES.values() if s['active'])}/3\n"
            f"🌐 Dashboard: Disponível\n\n"
            "✅ Sistema operacional e monitorando mercados..."
        )
        bot.send_message(CHAT_ID, startup_msg)
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem de início: {e}")
    
    # Inicia threads
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    telegram_thread = threading.Thread(target=run_telegram_bot, daemon=True)
    
    flask_thread.start()
    telegram_thread.start()
    
    # Executa verificador de sinais na thread principal
    try:
        run_signal_checker()
    except KeyboardInterrupt:
        logger.info("\nBot encerrado pelo usuário")
        shutdown_msg = "🛑 <b>Bot encerrado</b>\nSistema desligado pelo usuário."
        try:
            bot.send_message(CHAT_ID, shutdown_msg)
        except:
            pass
    except Exception as e:
        logger.error(f"Erro fatal: {e}")
        shutdown_msg = f"💥 <b>Erro fatal</b>\n{e}"
        try:
            bot.send_message(CHAT_ID, shutdown_msg)
        except:
            pass

if __name__ == "__main__":
    main()
