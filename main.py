import telebot
import requests
import pandas as pd
import time
import schedule
import threading
from flask import Flask
import os

# Pega as variáveis de ambiente do Render (seguras)
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

if not TELEGRAM_TOKEN or not CHAT_ID:
    print("Erro: TELEGRAM_TOKEN ou CHAT_ID não configurados!")
    exit(1)

bot = telebot.TeleBot(TELEGRAM_TOKEN)

def get_binance_data(symbol='BTCUSDT', interval='1h', limit=500):
    url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}'
    response = requests.get(url)
    data = response.json()
    df = pd.DataFrame(data, columns=['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_asset_volume', 'number_of_trades', 'taker_buy_base', 'taker_buy_quote', 'ignore'])
    df['close'] = df['close'].astype(float)
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    df.set_index('open_time', inplace=True)
    return df

def generate_signal(df, symbol):
    df['MA50'] = df['close'].rolling(window=50).mean()
    df['MA200'] = df['close'].rolling(window=200).mean()
    
    last_row = df.iloc[-1]
    prev_row = df.iloc[-2]
    
    if pd.notna(prev_row['MA50']) and pd.notna(last_row['MA50']):
        if prev_row['MA50'] < prev_row['MA200'] and last_row['MA50'] > last_row['MA200']:
            entry = last_row['close']
            tp = entry * 1.05  # +5%
            sl = entry * 0.97  # -3% (volatilidade cripto)
            return f"🚀 COMPRA {symbol}\nPreço: {entry:.2f}\nTP: {tp:.2f} (+5%)\nSL: {sl:.2f}"
        elif prev_row['MA50'] > prev_row['MA200'] and last_row['MA50'] < last_row['MA200']:
            entry = last_row['close']
            tp = entry * 0.95
            sl = entry * 1.03
            return f"🔻 VENDA {symbol}\nPreço: {entry:.2f}\nTP: {tp:.2f} (-5%)\nSL: {sl:.2f}"
    return None

def check_signals():
    symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT']  # Adicione mais se quiser
    for symbol in symbols:
        try:
            df = get_binance_data(symbol)
            signal = generate_signal(df, symbol)
            if signal:
                bot.send_message(CHAT_ID, signal)
                print(f"Sinal enviado: {symbol}")
        except Exception as e:
            print(f"Erro em {symbol}: {e}")

# Flask para manter o Render "acordado"
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot de sinais cripto rodando! 🚀"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def run_bot():
    schedule.every(15).minutes.do(check_signals)  # Verifica a cada 15 minutos
    # Envia mensagem de inicialização
    bot.send_message(CHAT_ID, "🤖 Bot de sinais iniciado! Verificando a cada 15 minutos.")
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == '__main__':
    threading.Thread(target=run_flask).start()
    run_bot()
