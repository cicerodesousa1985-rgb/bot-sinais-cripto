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
            tp = entry * 1.05
            sl = entry * 0.97
            return f"🚀 COMPRA {symbol}\nPreço: {entry:.2f}\nTP: {tp:.2f} (+5%)\nSL: {sl:.2f}"
        elif prev_row['MA50'] > prev_row['MA200'] and last_row['MA50'] < last_row['MA200']:
            entry = last_row['close']
            tp = entry * 0.95
            sl = entry * 1.03
            return f"🔻 VENDA {symbol}\nPreço: {entry:.2f}\nTP: {tp:.2f} (-5%)\nSL: {sl:.2f}"
    return None

def check_signals():
    symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT']
    for symbol in symbols:
        try:
            df = get_binance_data(symbol)
            signal = generate_signal(df, symbol)
            if signal:
                bot.send_message(CHAT_ID, signal)
                print(f"Sinal enviado: {symbol}")
        except Exception as e:
            print(f"Erro em {symbol}: {e}")

# Flask com dashboard bonito diretamente no código
app = Flask(__name__)

@app.route('/')
def home():
    return '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot Sinais Cripto - Dashboard</title>
    <style>
        body { font-family: 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 0; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        header { text-align: center; padding: 60px 20px; background: linear-gradient(135deg, #1e293b, #0f172a); border-bottom: 3px solid #60a5fa; }
        h1 { font-size: 3rem; margin: 0; color: #60a5fa; }
        h2 { color: #60a5fa; border-bottom: 2px solid #334155; padding-bottom: 10px; }
        .status { text-align: center; padding: 20px; font-size: 1.4rem; background: #1e293b; border-radius: 12px; margin: 20px 0; }
        .online { color: #34d399; font-weight: bold; }
        .card { background: #1e293b; border-radius: 12px; padding: 25px; margin: 20px 0; box-shadow: 0 6px 25px rgba(0,0,0,0.4); }
        .signals { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
        .signal { background: #334155; padding: 20px; border-radius: 12px; border-left: 6px solid #60a5fa; }
        .buy { border-left-color: #34d399; }
        .sell { border-left-color: #f87171; }
        .pair-list { line-height: 2rem; font-size: 1.1rem; }
        footer { text-align: center; padding: 40px; color: #64748b; font-size: 0.95rem; margin-top: 50px; border-top: 1px solid #334155; }
        @media (max-width: 768px) { h1 { font-size: 2.2rem; } .signals { grid-template-columns: 1fr; } }
    </style>
</head>
<body>
    <header>
        <h1>🚀 Bot de Sinais Cripto</h1>
        <p>Dashboard em tempo real • Estratégia: Cruzamento de Médias Móveis</p>
    </header>

    <div class="container">
        <div class="status">
            <strong>Status do Bot:</strong> <span class="online">● ONLINE E ATIVO</span><br>
            <small>Verificando sinais a cada 15 minutos • 24/7 no Render</small>
        </div>

        <div class="card">
            <h2>📊 Últimos Sinais Enviados</h2>
            <div class="signals">
                <p style="text-align:center; color:#94a3b8; grid-column: 1 / -1;">
                    Aguardando primeiros sinais...<br>
                    <small>Eles aparecerão aqui e no Telegram automaticamente</small>
                </p>
            </div>
        </div>

        <div class="card">
            <h2>📈 Pares Monitorados</h2>
            <div class="pair-list">
                <ul>
                    <li>🪙 BTC/USDT</li>
                    <li>🪙 ETH/USDT</li>
                    <li>🪙 SOL/USDT</li>
                    <li>🪙 BNB/USDT</li>
                </ul>
            </div>
            <p><strong>Estratégia:</strong> Cruzamento MA50 × MA200 (timeframe 1h)</p>
            <p><strong>Take Profit:</strong> +5% &nbsp;|&nbsp; <strong>Stop Loss:</strong> ~3%</p>
        </div>

        <div class="card">
            <h2>ℹ️ Informações</h2>
            <p>Sinais enviados diretamente para o Telegram.</p>
            <p>Rodando 24/7 de graça no Render + UptimeRobot.</p>
        </div>
    </div>

    <footer>
        Bot criado por você • Janeiro/2026 • Todos os direitos reservados ©
    </footer>
</body>
</html>
    '''

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def run_bot():
    schedule.every(15).minutes.do(check_signals)
    bot.send_message(CHAT_ID, "🤖 Bot de sinais iniciado! Verificando a cada 15 minutos.")
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == '__main__':
    threading.Thread(target=run_flask).start()
    run_bot()
