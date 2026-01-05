import os
import time
import threading
import requests
import logging
from datetime import datetime
from flask import Flask

# =========================
# CONFIGURAÇÃO
# =========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

signals_paused = False
last_signals = []

# =========================
# CACHE & HISTÓRICO
# =========================
indicator_history = {}
kline_cache = {}
CACHE_TTL = 30

# =========================
# CONFIGURAÇÃO DO BOT
# =========================
TIMEFRAMES = ["1m", "5m", "15m"]

PAIRS = [
    "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","AVAXUSDT",
    "DOGEUSDT","DOTUSDT","TRXUSDT","LINKUSDT","MATICUSDT","LTCUSDT"
]

STRATEGIES = {
    "RSI_EXTREME": {"active": True},
    "STOCH_FAST": {"active": True},
    "PRICE_BREAKOUT": {"active": True},
    "VOLUME_SPIKE": {"active": True},
    "EMA_CROSS": {"active": True},
    "MACD": {"active": True},
}

# =========================
# BINANCE API COM CACHE
# =========================
def get_binance_klines(symbol, interval="1m", limit=100):
    key = (symbol, interval)
    now = time.time()

    if key in kline_cache:
        data, ts = kline_cache[key]
        if now - ts < CACHE_TTL:
            return data

    logger.info(f"Requisitando klines: {symbol} {interval} limit={limit}")
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            kline_cache[key] = (data, now)
            logger.info(f"Sucesso ao pegar klines para {symbol} {interval}")
            return data
        else:
            logger.warning(f"Erro HTTP {r.status_code} para {symbol} {interval}: {r.text}")
    except Exception as e:
        logger.error(f"Erro ao conectar Binance {symbol} {interval}: {e}")

    logger.warning(f"Falha total em pegar klines para {symbol} {interval} - retornando None")
    return None

# =========================
# INDICADORES
# =========================
def calculate_ema(prices, period):
    if len(prices) < period:
        return prices[-1]
    ema = sum(prices[:period]) / period
    mult = 2 / (period + 1)
    for p in prices[period:]:
        ema = (p - ema) * mult + ema
    return ema

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i - 1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_stochastic(prices, period=14):
    if len(prices) < period:
        return 50
    low = min(prices[-period:])
    high = max(prices[-period:])
    if high == low:
        return 50
    return (prices[-1] - low) / (high - low) * 100

def calculate_macd(prices):
    return calculate_ema(prices, 12) - calculate_ema(prices, 26)

def calculate_indicators(prices, volumes, symbol, tf):
    ind = {
        "price": prices[-1],
        "ema9": calculate_ema(prices, 9),
        "ema21": calculate_ema(prices, 21),
        "rsi": calculate_rsi(prices),
        "stoch": calculate_stochastic(prices),
        "recent_high": max(prices[-20:]),
        "recent_low": min(prices[-20:]),
        "volume": volumes[-1],
        "volume_avg": sum(volumes[-20:]) / 20,
        "prices": prices,
    }
    prev = indicator_history.get((symbol, tf))
    indicator_history[(symbol, tf)] = ind
    return ind, prev

# =========================
# ESTRATÉGIAS
# =========================
def apply_strategies(ind, prev):
    signals = []

    if STRATEGIES["RSI_EXTREME"]["active"]:
        if ind["rsi"] < 30:
            signals.append(("COMPRA", "RSI OVERSOLD", 1.2))
        elif ind["rsi"] > 70:
            signals.append(("VENDA", "RSI OVERBOUGHT", 1.2))

    if STRATEGIES["STOCH_FAST"]["active"]:
        if ind["stoch"] < 20:
            signals.append(("COMPRA", "STOCH OVERSOLD", 1.1))
        elif ind["stoch"] > 80:
            signals.append(("VENDA", "STOCH OVERBOUGHT", 1.1))

    if STRATEGIES["PRICE_BREAKOUT"]["active"]:
        if ind["price"] > ind["recent_high"]:
            signals.append(("COMPRA", "BREAKOUT ALTA", 1.4))
        elif ind["price"] < ind["recent_low"]:
            signals.append(("VENDA", "BREAKDOWN BAIXA", 1.4))

    if STRATEGIES["VOLUME_SPIKE"]["active"]:
        if ind["volume"] > ind["volume_avg"] * 3:
            direction = "COMPRA" if prev and ind["price"] > prev["price"] else "VENDA"
            signals.append((direction, "VOLUME SPIKE", 1.3))

    if STRATEGIES["EMA_CROSS"]["active"] and prev:
        if ind["ema9"] > ind["ema21"] and prev["ema9"] <= prev["ema21"]:
            signals.append(("COMPRA", "EMA GOLDEN CROSS", 1.3))
        elif ind["ema9"] < ind["ema21"] and prev["ema9"] >= prev["ema21"]:
            signals.append(("VENDA", "EMA DEATH CROSS", 1.3))

    if STRATEGIES["MACD"]["active"] and prev:
        macd = calculate_macd(ind["prices"])
        prev_macd = calculate_macd(prev["prices"])
        if macd > 0 and prev_macd <= 0:
            signals.append(("COMPRA", "MACD BULLISH", 1.2))
        elif macd < 0 and prev_macd >= 0:
            signals.append(("VENDA", "MACD BEARISH", 1.2))

    return signals

# =========================
# ANÁLISE MULTI-TIMEFRAME
# =========================
def analyze_symbol(symbol):
    buy_score = sell_score = 0
    reasons = []
    price = None
    used_tfs = []

    for tf in TIMEFRAMES:
        klines = get_binance_klines(symbol, tf)
        if not klines:
            continue

        closes = [float(k[4]) for k in klines]
        volumes = [float(k[5]) for k in klines]

        ind, prev = calculate_indicators(closes, volumes, symbol, tf)
        price = ind["price"]

        signals = apply_strategies(ind, prev)
        if not signals:
            continue

        used_tfs.append(tf)
        for d, r, w in signals:
            reasons.append(f"{tf}: {r}")
            buy_score += w if d == "COMPRA" else 0
            sell_score += w if d == "VENDA" else 0

    logger.info(f"{symbol}: Dados OK em {len(used_tfs)} TFs ({', '.join(used_tfs or ['nenhum'])}). "
                f"Buy_score: {buy_score:.1f} | Sell_score: {sell_score:.1f}")

    if len(used_tfs) < 2:
        return None

    direction = "COMPRA" if buy_score > sell_score else "VENDA"
    score = max(buy_score, sell_score)
    confidence = min(score / 6, 1)

    if confidence < 0.5:
        return None

    return {
        "symbol": symbol,
        "direction": direction,
        "price": price,
        "confidence": confidence,
        "score": score,
        "reasons": reasons[:3],
        "timestamp": datetime.now(),
    }

# =========================
# TELEGRAM
# =========================
def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.warning("Telegram não configurado (TOKEN ou CHAT_ID ausente)")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg},
            timeout=10
        )
    except Exception as e:
        logger.error(f"Erro ao enviar Telegram: {e}")

def send_signal(signal):
    emoji = "🚀" if signal["direction"] == "COMPRA" else "🔻"
    msg = (
        f"{emoji} *{signal['direction']}*\n"
        f"Par: `{signal['symbol']}`\n"
        f"Preço: `${signal['price']:.4f}`\n"
        f"Confiança: {signal['confidence']:.0%}\n"
        f"Razões:\n" + "\n".join(signal["reasons"])
    )
    send_telegram(msg)
    last_signals.append(signal)
    last_signals[:] = last_signals[-10:]

# =========================
# DASHBOARD WEB BONITÃO
# =========================
@app.route("/")
def dashboard():
    strategies_html = "".join(
        f'<span class="px-3 py-1 rounded-full text-xs font-bold {"bg-green-600" if v["active"] else "bg-red-600"}">'
        f'{k.replace("_", " ")}</span>'
        for k, v in STRATEGIES.items()
    )

    signals_table = ""
    if last_signals:
        signals_table = """
        <table class="w-full table-auto border-collapse">
            <thead>
                <tr class="bg-gray-800">
                    <th class="px-4 py-3 text-left">Direção</th>
                    <th class="px-4 py-3 text-left">Par</th>
                    <th class="px-4 py-3 text-right">Preço</th>
                    <th class="px-4 py-3 text-right">Confiança</th>
                    <th class="px-4 py-3 text-left">Motivos</th>
                    <th class="px-4 py-3 text-right">Horário</th>
                </tr>
            </thead>
            <tbody>
        """
        for s in reversed(last_signals):
            emoji = "🟢" if s["direction"] == "COMPRA" else "🔴"
            color = "text-green-400" if s["direction"] == "COMPRA" else "text-red-400"
            time_str = s["timestamp"].strftime("%H:%M:%S")
            reasons = " • ".join(s["reasons"])
            signals_table += f"""
                <tr class="border-b border-gray-700 hover:bg-gray-800 transition">
                    <td class="px-4 py-3 {color} font-bold">{emoji} {s['direction']}</td>
                    <td class="px-4 py-3 font-mono">{s['symbol']}</td>
                    <td class="px-4 py-3 text-right font-mono">${s['price']:,.2f}</td>
                    <td class="px-4 py-3 text-right">{int(s['confidence']*100)}%</td>
                    <td class="px-4 py-3 text-sm text-gray-400">{reasons}</td>
                    <td class="px-4 py-3 text-right text-xs text-gray-500">{time_str}</td>
                </tr>
            """
        signals_table += "</tbody></table>"
    else:
        signals_table = '<p class="text-gray-400 text-center py-8">Aguardando primeiros sinais...</p>'

    return f"""
    <!DOCTYPE html>
    <html lang="pt-BR" class="bg-gray-900 text-gray-100">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>🤖 Bot Sinais Cripto</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css" rel="stylesheet">
        <style>
            body {{ font-family: 'Segoe UI', sans-serif; }}
            .blink {{ animation: blink 1s infinite; }}
            @keyframes blink {{ 50% {{ opacity: 0.5; }} }}
        </style>
    </head>
    <body class="min-h-screen">
        <div class="container mx-auto p-6 max-w-6xl">
            <div class="text-center mb-10">
                <h1 class="text-5xl font-bold mb-4 bg-gradient-to-r from-blue-500 to-purple-600 bg-clip-text text-transparent">
                    🤖 Bot de Sinais Cripto
                </h1>
                <p class="text-2xl flex items-center justify-center gap-3">
                    Status: <span class="text-green-400 blink">● ONLINE</span>
                    <span id="countdown" class="text-yellow-400 font-mono">60s até próxima scan</span>
                </p>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-10">
                <div class="bg-gray-800 rounded-2xl p-6 border border-gray-700">
                    <h3 class="text-lg text-gray-400 mb-2">Pares Monitorados</h3>
                    <p class="text-3xl font-bold">{len(PAIRS)}</p>
                    <p class="text-sm text-gray-500 mt-2">{', '.join(PAIRS[:6])}{"..." if len(PAIRS)>6 else ""}</p>
                </div>
                <div class="bg-gray-800 rounded-2xl p-6 border border-gray-700">
                    <h3 class="text-lg text-gray-400 mb-2">Timeframes</h3>
                    <p class="text-3xl font-bold">{len(TIMEFRAMES)}</p>
                    <p class="text-sm text-gray-500 mt-2">Multi-timeframe: {', '.join(TIMEFRAMES)}</p>
                </div>
                <div class="bg-gray-800 rounded-2xl p-6 border border-gray-700">
                    <h3 class="text-lg text-gray-400 mb-2">Sinais Enviados</h3>
                    <p class="text-3xl font-bold">{len(last_signals)}</p>
                    <p class="text-sm text-gray-500 mt-2">Últimos 10 exibidos</p>
                </div>
            </div>

            <div class="bg-gray-800 rounded-2xl p-6 mb-10 border border-gray-700">
                <h2 class="text-2xl font-bold mb-4 flex items-center gap-3">
                    <i class="fas fa-brain text-purple-500"></i> Estratégias Ativas
                </h2>
                <div class="flex flex-wrap gap-3">
                    {strategies_html}
                </div>
            </div>

            <div class="bg-gray-800 rounded-2xl p-6 border border-gray-700">
                <h2 class="text-2xl font-bold mb-6 flex items-center gap-3">
                    <i class="fas fa-bolt text-yellow-500"></i> Últimos Sinais Gerados
                </h2>
                <div class="overflow-x-auto">
                    {signals_table}
                </div>
            </div>

            <div class="text-center mt-12 text-gray-500 text-sm">
                Bot rodando desde {datetime.now().strftime("%d/%m/%Y %H:%M")} • Varredura a cada 60s
            </div>
        </div>

        <script>
            let seconds = 60;
            setInterval(() => {
                seconds = seconds <= 0 ? 60 : seconds - 1;
                document.getElementById('countdown').innerText = seconds + 's até próxima scan';
            }, 1000);
        </script>
    </body>
    </html>
    """

# =========================
# LOOP PRINCIPAL
# =========================
def run_bot():
    logger.info("🤖 BOT INICIADO - Iniciando varredura dos pares")
    while True:
        logger.info("=== NOVA VARREDURA INICIADA ===")
        for symbol in PAIRS:
            signal = analyze_symbol(symbol)
            if signal:
                logger.info(f"SINAL GERADO: {signal['direction']} {symbol} - Confiança {signal['confidence']:.0%}")
                send_signal(signal)
                time.sleep(1)
        logger.info("Varredura concluída. Dormindo 60s...")
        time.sleep(60)

# =========================
# MAIN
# =========================
def main():
    threading.Thread(target=run_bot, daemon=True).start()
    logger.info(f"Dashboard disponível em http://0.0.0.0:10000")
    app.run(host="0.0.0.0", port=10000)

if __name__ == "__main__":
    main()
