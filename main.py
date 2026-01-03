import telebot
import requests
import pandas as pd
import time
import schedule
import threading
from flask import Flask
import os
from datetime import datetime

# =========================
# CONFIGURAÇÕES
# =========================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

if not TELEGRAM_TOKEN or not CHAT_ID:
    raise Exception("Configure TELEGRAM_TOKEN e CHAT_ID")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

signals_paused = False
last_signals = []

PAIRS = [
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT',
    'ADAUSDT', 'XRPUSDT', 'DOGEUSDT', 'LINKUSDT', 'AVAXUSDT'
]

# =========================
# BINANCE DATA
# =========================
def get_binance_data(symbol, interval='1m', limit=300):
    url = f'https://api.binance.com/api/v3/klines'
    params = {'symbol': symbol, 'interval': interval, 'limit': limit}
    data = requests.get(url, params=params, timeout=10).json()

    df = pd.DataFrame(data, columns=[
        'open_time','open','high','low','close','volume',
        'close_time','qav','trades','tbb','tbq','ignore'
    ])

    df[['open','high','low','close','volume']] = df[['open','high','low','close','volume']].astype(float)
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    df.set_index('open_time', inplace=True)
    return df

# =========================
# INDICADORES
# =========================
def rsi(df, period=14):
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period-1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period-1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    df['RSI'] = 100 - (100 / (1 + rs))
    return df

def macd(df):
    ema12 = df['close'].ewm(span=12).mean()
    ema26 = df['close'].ewm(span=26).mean()
    df['MACD'] = ema12 - ema26
    df['SIGNAL'] = df['MACD'].ewm(span=9).mean()
    return df

# =========================
# ESTRATÉGIAS
# =========================
def ema_vwap_strategy(df):
    df['EMA9'] = df['close'].ewm(span=9).mean()
    df['EMA21'] = df['close'].ewm(span=21).mean()

    tp = (df['high'] + df['low'] + df['close']) / 3
    df['VWAP'] = (tp * df['volume']).cumsum() / df['volume'].cumsum()

    last, prev = df.iloc[-1], df.iloc[-2]

    if last['close'] > last['VWAP'] and last['EMA9'] > last['EMA21'] and prev['EMA9'] <= prev['EMA21']:
        return 'buy'

    if last['close'] < last['VWAP'] and last['EMA9'] < last['EMA21'] and prev['EMA9'] >= prev['EMA21']:
        return 'sell'

    return None

def rsi_scalping_strategy(df):
    df = rsi(df)
    r = df['RSI'].iloc[-1]

    if 30 < r < 45:
        return 'buy'
    if 55 < r < 70:
        return 'sell'
    return None

def macd_strategy(df):
    df = macd(df)
    last, prev = df.iloc[-1], df.iloc[-2]

    if prev['MACD'] < prev['SIGNAL'] and last['MACD'] > last['SIGNAL']:
        return 'buy'
    if prev['MACD'] > prev['SIGNAL'] and last['MACD'] < last['SIGNAL']:
        return 'sell'
    return None

def volume_filter(df):
    return df['volume'].iloc[-1] > df['volume'].rolling(20).mean().iloc[-1]

# =========================
# GERAÇÃO DE SINAL
# =========================
def generate_signal(df, symbol):
    if not volume_filter(df):
        return None

    results = [
        ema_vwap_strategy(df),
        rsi_scalping_strategy(df),
        macd_strategy(df)
    ]

    buys = results.count('buy')
    sells = results.count('sell')

    if buys >= 2 or sells >= 2:
        entry = df['close'].iloc[-1]
        direction = 'COMPRA' if buys >= 2 else 'VENDA'
        emoji = '🚀' if buys >= 2 else '🔻'

        tp = entry * (1.003 if buys >= 2 else 0.997)
        sl = entry * (0.998 if buys >= 2 else 1.002)

        text = (
            f"{emoji} SCALPING {direction}\n"
            f"Par: {symbol}\n"
            f"Entrada: {entry:.4f}\n"
            f"TP: {tp:.4f} (0,3%)\n"
            f"SL: {sl:.4f} (0,2%)\n"
            f"TF: 1m\n"
            f"Hora: {datetime.now().strftime('%H:%M:%S')}"
        )

        last_signals.append(text)
        del last_signals[:-10]
        return text
    return None

# =========================
# LOOP PRINCIPAL
# =========================
def check_signals():
    if signals_paused:
        return

    for pair in PAIRS:
        try:
            df = get_binance_data(pair)
            signal = generate_signal(df, pair)
            if signal:
                bot.send_message(CHAT_ID, signal)
        except Exception as e:
            print(pair, e)

# =========================
# FLASK DASHBOARD
# =========================
app = Flask(__name__)

@app.route('/')
def home():
    html = ''.join([f"<pre>{s}</pre><hr>" for s in reversed(last_signals)])
    return f"<h1>Bot Scalping Cripto - Online</h1>{html}"

@app.route('/pause')
def pause():
    global signals_paused
    signals_paused = True
    return "Sinais pausados"

@app.route('/resume')
def resume():
    global signals_paused
    signals_paused = False
    return "Sinais retomados"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def run_bot():
    schedule.every(1).minutes.do(check_signals)
    bot.send_message(CHAT_ID, "🤖 Bot de Scalping Cripto ATIVO (somente sinais)")
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    run_bot()
