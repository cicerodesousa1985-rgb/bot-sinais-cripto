import telebot
import requests
import pandas as pd
import time
import schedule
import threading
from flask import Flask
import os

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

if not TELEGRAM_TOKEN or not CHAT_ID:
    print("Erro: TELEGRAM_TOKEN ou CHAT_ID não configurados!")
    exit(1)

bot = telebot.TeleBot(TELEGRAM_TOKEN)

def get_binance_data(symbol='BTCUSDT', interval='5m', limit=500):
    url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}'
    response = requests.get(url)
    data = response.json()
    df = pd.DataFrame(data, columns=['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_asset_volume', 'number_of_trades', 'taker_buy_base', 'taker_buy_quote', 'ignore'])
    df['close'] = df['close'].astype(float)
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    df.set_index('open_time', inplace=True)
    return df

def ma_crossover(df):
    df['MA50'] = df['close'].rolling(window=50).mean()
    df['MA200'] = df['close'].rolling(window=200).mean()
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    if pd.notna(prev['MA50']) and pd.notna(last['MA50']):
        if prev['MA50'] < prev['MA200'] and last['MA50'] > last['MA200']:
            return 'buy'
        elif prev['MA50'] > prev['MA200'] and last['MA50'] < last['MA200']:
            return 'sell'
    return None

def rsi(df, period=14):
    delta = df['close'].diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ema_up = up.ewm(com=period-1, min_periods=period).mean()
    ema_down = down.ewm(com=period-1, min_periods=period).mean()
    rs = ema_up / ema_down
    df['RSI'] = 100 - (100 / (1 + rs))
    return df

def rsi_strategy(df):
    df = rsi(df)
    last_rsi = df['RSI'].iloc[-1]
    if last_rsi < 30:
        return 'buy'
    elif last_rsi > 70:
        return 'sell'
    return None

def macd(df, short=12, long=26, signal=9):
    short_ema = df['close'].ewm(span=short, min_periods=short-1).mean()
    long_ema = df['close'].ewm(span=long, min_periods=long-1).mean()
    df['MACD'] = short_ema - long_ema
    df['Signal'] = df['MACD'].ewm(span=signal, min_periods=signal-1).mean()
    return df

def macd_strategy(df):
    df = macd(df)
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    if pd.notna(prev['MACD']) and pd.notna(last['MACD']):
        if prev['MACD'] < prev['Signal'] and last['MACD'] > last['Signal']:
            return 'buy'
        elif prev['MACD'] > prev['Signal'] and last['MACD'] < last['Signal']:
            return 'sell'
    return None

def generate_signal(df, symbol):
    strategies = [ma_crossover(df), rsi_strategy(df), macd_strategy(df)]
    buys = strategies.count('buy')
    sells = strategies.count('sell')
    
    if buys >= 2 or sells >= 2:
        entry = df['close'].iloc[-1]
        direction = 'COMPRA' if buys >= 2 else 'VENDA'
        emoji = '🚀' if buys >= 2 else '🔻'
        tp = entry * 1.05 if buys >= 2 else entry * 0.95
        sl = entry * 0.97 if buys >= 2 else entry * 1.03
        return f"{emoji} SINAL DE {direction} para {symbol}!\nEntry: {entry:.2f}\nTP: {tp:.2f} (+5%)\nSL: {sl:.2f}"
    return None

def check_signals():
    symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'ADAUSDT', 'XRPUSDT', 'DOGEUSDT', 'LINKUSDT', 'AVAXUSDT']
    for symbol in symbols:
        try:
            df = get_binance_data(symbol)
            signal = generate_signal(df, symbol)
            if signal:
                bot.send_message(CHAT_ID, signal)
                print(f"Sinal enviado: {symbol}")
        except Exception as e:
            print(f"Erro em {symbol}: {e}")

app = Flask(__name__)

@app.route('/')
def home():
    return '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot Sinais Cripto</title>
    <style>
        body { font-family: Arial, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 0; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        header { text-align: center; padding: 50px 20px; background: linear-gradient(135deg, #1e293b, #0f172a); }
        h1 { font-size: 3rem; color: #60a5fa; }
        .status { text-align: center; padding: 20px; background: #1e293b; border-radius: 12px; margin: 20px 0; }
        .online { color: #34d399; }
        .card { background: #1e293b; border-radius: 12px; padding: 25px; margin: 20px 0; }
        .pair-list ul { list-style: none; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
        .pair-list li { background: #334155; padding: 15px; border-radius: 10px; text-align: center; }
        footer { text-align: center; padding: 40px; color: #64748b; }
    </style>
</head>
<body>
    <header>
        <h1>🚀 Bot de Sinais Cripto</h1>
        <p>Dashboard em tempo real • 9 Pares • Timeframe 5min</p>
    </header>

    <div class="container">
        <div class="status">
            <strong>Status do Bot:</strong> <span class="online">● ONLINE E ATIVO</span><br>
            <small>Verificando a cada 5 minutos</small>
        </div>

        <div class="card">
            <h2>📊 Últimos Sinais Enviados</h2>
            <p style="text-align:center;">Aguardando sinais...</p>
        </div>

        <div class="card">
            <h2>📈 Pares Monitorados</h2>
            <div class="pair-list">
                <ul>
                    <li>BTC/USDT</li>
                    <li>ETH/USDT</li>
                    <li>SOL/USDT</li>
                    <li>BNB/USDT</li>
                    <li>ADA/USDT</li>
                    <li>XRP/USDT</li>
                    <li>DOGE/USDT</li>
                    <li>LINK/USDT</li>
                    <li>AVAX/USDT</li>
                </ul>
            </div>
        </div>
    </div>

    <footer>
        Bot criado por você • Janeiro 2026
    </footer>
</body>
</html>
    '''

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def run_bot():
    schedule.every(5).minutes.do(check_signals)
    bot.send_message(CHAT_ID, "🤖 Bot corrigido! Dashboard leve ativado novamente.")
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == '__main__':
    threading.Thread(target=run_flask).start()
    run_bot()
