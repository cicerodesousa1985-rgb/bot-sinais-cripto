import telebot
import requests
import pandas as pd
import time
import schedule
import threading
from flask import Flask
import os

# Variáveis de ambiente (seguras no Render)
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

# Flask com dashboard ULTRA MODERNO (Tailwind + Glassmorphism)
app = Flask(__name__)

@app.route('/')
def home():
    return '''
<!DOCTYPE html>
<html lang="pt-BR" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot Sinais Cripto AI</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css" rel="stylesheet">
    <style>
        body { background: linear-gradient(135deg, #0f0c29, #302b63, #24243e); min-height: 100vh; }
        .glass { background: rgba(255, 255, 255, 0.05); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.1); }
        .glow { box-shadow: 0 0 30px rgba(59, 130, 246, 0.4); }
    </style>
</head>
<body class="text-gray-100">
    <div class="container mx-auto px-4 py-8 max-w-7xl">
        <header class="text-center mb-12">
            <h1 class="text-5xl md:text-6xl font-bold bg-gradient-to-r from-blue-400 to-purple-600 bg-clip-text text-transparent">
                <i class="fas fa-robot mr-4"></i> Bot Sinais Cripto AI
            </h1>
            <p class="text-xl mt-4 text-gray-300">Dashboard Inteligente • Timeframe 5min • 9 Pares Monitorados</p>
        </header>

        <div class="glass rounded-3xl p-10 text-center glow mb-10">
            <h2 class="text-3xl font-bold mb-4"><i class="fas fa-satellite-dish text-green-400 mr-3"></i> Status do Bot</h2>
            <p class="text-2xl"><span class="text-green-400 font-bold">● ONLINE E ATIVO</span></p>
            <p class="text-lg mt-3 text-gray-300">Verificando sinais a cada 5 minutos • Estratégias combinadas</p>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-10">
            <div class="glass rounded-3xl p-8 glow">
                <h2 class="text-2xl font-bold mb-6 flex items-center"><i class="fas fa-bell text-yellow-400 mr-3"></i> Últimos Sinais Enviados</h2>
                <div id="signals-list" class="space-y-4">
                    <p class="text-center text-gray-400 py-12">Aguardando sinais de alta precisão...<br><small class="text-sm">Apenas sinais confirmados por 2+ estratégias</small></p>
                </div>
            </div>

            <div class="glass rounded-3xl p-8 glow">
                <h2 class="text-2xl font-bold mb-6 flex items-center"><i class="fas fa-coins text-orange-400 mr-3"></i> Pares Monitorados</h2>
                <div class="grid grid-cols-2 md:grid-cols-3 gap-4 text-center">
                    <div class="bg-blue-900/40 rounded-xl p-4 glow"><strong>BTC/USDT</strong></div>
                    <div class="bg-purple-900/40 rounded-xl p-4 glow"><strong>ETH/USDT</strong></div>
                    <div class="bg-green-900/40 rounded-xl p-4 glow"><strong>SOL/USDT</strong></div>
                    <div class="bg-yellow-900/40 rounded-xl p-4 glow"><strong>BNB/USDT</strong></div>
                    <div class="bg-pink-900/40 rounded-xl p-4 glow"><strong>ADA/USDT</strong></div>
                    <div class="bg-indigo-900/40 rounded-xl p-4 glow"><strong>XRP/USDT</strong></div>
                    <div class="bg-orange-900/40 rounded-xl p-4 glow"><strong>DOGE/USDT</strong></div>
                    <div class="bg-teal-900/40 rounded-xl p-4 glow"><strong>LINK/USDT</strong></div>
                    <div class="bg-red-900/40 rounded-xl p-4 glow"><strong>AVAX/USDT</strong></div>
                </div>
            </div
