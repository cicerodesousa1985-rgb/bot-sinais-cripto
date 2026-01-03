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

# =========================
# CONFIGURAÇÃO DE LOG
# =========================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
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

# Configuração de pares
PAIRS = [
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT',
    'ADAUSDT', 'XRPUSDT', 'DOGEUSDT', 'LINKUSDT', 'AVAXUSDT'
]

# Configurações de estratégia
STRATEGIES = {
    'ema_vwap': {'weight': 1.0},
    'rsi_scalping': {'weight': 0.8},
    'macd': {'weight': 0.9}
}

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
    
    signal_cache[cache_key] = current_time
    return False

def generate_signal(df: pd.DataFrame, symbol: str) -> Optional[str]:
    """Gera sinal baseado em múltiplas estratégias"""
    try:
        if not volume_filter(df):
            return None
        
        # Executa estratégias
        signals = {
            'ema_vwap': ema_vwap_strategy(df),
            'rsi_scalping': rsi_scalping_strategy(df),
            'macd': macd_strategy(df)
        }
        
        # Contagem ponderada
        buy_score = 0
        sell_score = 0
        
        for strategy, result in signals.items():
            weight = STRATEGIES[strategy]['weight']
            if result == 'buy':
                buy_score += weight
            elif result == 'sell':
                sell_score += weight
        
        # Determina direção
        if buy_score >= 1.5 or sell_score >= 1.5:
            if buy_score > sell_score and not is_signal_duplicate(symbol, 'buy'):
                direction = 'COMPRA'
                emoji = '🚀'
                tp_mult = 1.003
                sl_mult = 0.998
            elif sell_score > buy_score and not is_signal_duplicate(symbol, 'sell'):
                direction = 'VENDA'
                emoji = '🔻'
                tp_mult = 0.997
                sl_mult = 1.002
            else:
                return None
            
            entry = df['close'].iloc[-1]
            tp = entry * tp_mult
            sl = entry * sl_mult
            
            signal_text = (
                f"{emoji} <b>SCALPING {direction}</b>\n"
                f"Par: <code>{symbol}</code>\n"
                f"Entrada: <b>{entry:.4f}</b>\n"
                f"TP: {tp:.4f} (0.3%)\n"
                f"SL: {sl:.4f} (0.2%)\n"
                f"TF: 1m\n"
                f"Hora: {datetime.now().strftime('%H:%M:%S')}\n"
                f"Confiança: {max(buy_score, sell_score):.1f}/3.0"
            )
            
            # Armazena último sinal
            last_signals.append({
                'time': datetime.now(),
                'symbol': symbol,
                'direction': direction,
                'entry': entry,
                'text': signal_text
            })
            
            # Mantém apenas últimos 20 sinais
            del last_signals[:-20]
            
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
                continue
            
            signal = generate_signal(df, pair)
            if signal:
                logger.info(f"Sinal encontrado para {pair}")
                bot.send_message(CHAT_ID, signal)
                time.sleep(1)  # Delay entre mensagens
                
        except Exception as e:
            logger.error(f"Erro ao processar {pair}: {e}")

# =========================
# COMANDOS TELEGRAM
# =========================
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """Comandos do bot no Telegram"""
    welcome_text = (
        "🤖 <b>Bot de Scalping Cripto</b>\n\n"
        "Comandos disponíveis:\n"
        "/status - Status do bot\n"
        "/pause - Pausar sinais\n"
        "/resume - Retomar sinais\n"
        "/pairs - Listar pares monitorados\n"
        "/signals - Últimos sinais"
    )
    bot.reply_to(message, welcome_text)

@bot.message_handler(commands=['status'])
def send_status(message):
    """Status do bot"""
    status = "⏸️ PAUSADO" if signals_paused else "🟢 ATIVO"
    text = f"Status: {status}\nPares: {len(PAIRS)}\nÚltimos sinais: {len(last_signals)}"
    bot.reply_to(message, text)

@bot.message_handler(commands=['pause'])
def pause_signals(message):
    """Pausa sinais"""
    global signals_paused
    signals_paused = True
    bot.reply_to(message, "⏸️ Sinais pausados")

@bot.message_handler(commands=['resume'])
def resume_signals(message):
    """Retoma sinais"""
    global signals_paused
    signals_paused = False
    bot.reply_to(message, "🟢 Sinais retomados")

# =========================
# DASHBOARD FLASK MELHORADO
# =========================
app = Flask(__name__)

@app.route('/')
def dashboard():
    """Dashboard com sinais recentes"""
    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Bot Scalping Cripto</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
            .container { max-width: 1000px; margin: 0 auto; }
            .header { background: #2c3e50; color: white; padding: 20px; border-radius: 10px; }
            .signal { background: white; padding: 15px; margin: 10px 0; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .buy { border-left: 5px solid #27ae60; }
            .sell { border-left: 5px solid #e74c3c; }
            .controls { margin: 20px 0; }
            .btn { padding: 10px 15px; margin: 5px; border: none; border-radius: 5px; cursor: pointer; }
            .pause { background: #e74c3c; color: white; }
            .resume { background: #27ae60; color: white; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🤖 Bot Scalping Cripto</h1>
                <p>Status: {{ '⏸️ PAUSADO' if paused else '🟢 ATIVO' }}</p>
                <p>Pares monitorados: {{ pairs_count }}</p>
                <div class="controls">
                    <a href="/pause" class="btn pause">Pausar Sinais</a>
                    <a href="/resume" class="btn resume">Retomar Sinais</a>
                </div>
            </div>
            
            <h2>Últimos Sinais ({{ signals_count }})</h2>
            {% for signal in signals %}
            <div class="signal {{ 'buy' if 'COMPRA' in signal.text else 'sell' }}">
                {{ signal.text|safe }}
                <small>{{ signal.time.strftime('%H:%M:%S') }}</small>
            </div>
            {% endfor %}
        </div>
    </body>
    </html>
    """
    
    return render_template_string(
        html_template,
        signals=reversed(last_signals[-20:]),
        signals_count=len(last_signals),
        pairs_count=len(PAIRS),
        paused=signals_paused
    )

@app.route('/pause')
def pause_web():
    global signals_paused
    signals_paused = True
    return "Sinais pausados <a href='/'>Voltar</a>"

@app.route('/resume')
def resume_web():
    global signals_payed
    signals_paused = False
    return "Sinais retomados <a href='/'>Voltar</a>"

# =========================
# THREADS E EXECUÇÃO
# =========================
def run_flask():
    """Executa servidor Flask em thread separada"""
    app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)

def run_telegram_bot():
    """Executa polling do Telegram em thread separada"""
    logger.info("Iniciando bot do Telegram...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)

def run_signal_checker():
    """Executa verificação de sinais periódica"""
    logger.info("Iniciando verificador de sinais...")
    schedule.every(1).minutes.do(check_signals)
    
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except Exception as e:
            logger.error(f"Erro no verificador de sinais: {e}")
            time.sleep(5)

if __name__ == "__main__":
    logger.info("Iniciando Bot de Scalping Cripto...")
    
    # Inicia threads
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    telegram_thread = threading.Thread(target=run_telegram_bot, daemon=True)
    
    flask_thread.start()
    telegram_thread.start()
    
    # Executa verificador de sinais na thread principal
    try:
        run_signal_checker()
    except KeyboardInterrupt:
        logger.info("Bot encerrado pelo usuário")
    except Exception as e:
        logger.error(f"Erro fatal: {e}")
