import os
import time
import threading
import requests
import logging
from datetime import datetime, timedelta
from flask import Flask, jsonify, request
from functools import wraps
from dotenv import load_dotenv
import psutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict, deque

# =========================
# CONFIGURAÇÃO
# =========================
load_dotenv()

class Config:
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    CHAT_ID = os.getenv("CHAT_ID")
    BOT_INTERVAL = int(os.getenv("BOT_INTERVAL", 60))
    MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", 0.5))
    ENABLE_WEB = os.getenv("ENABLE_WEB", "true").lower() == "true"
    API_KEY = os.getenv("API_KEY")
    MAX_WORKERS = int(os.getenv("MAX_WORKERS", 5))
    CACHE_TTL = int(os.getenv("CACHE_TTL", 30))
    FAILURE_THRESHOLD = int(os.getenv("FAILURE_THRESHOLD", 5))
    RECOVERY_TIMEOUT = int(os.getenv("RECOVERY_TIMEOUT", 60))

# =========================
# SETUP DE LOGGING
# =========================
def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # File handler (rotativo)
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            "bot.log",
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(logging.DEBUG)
        
        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)
        
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Erro configurando file handler: {e}")
        console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(console_handler)
    
    return logger

logger = setup_logging()

# =========================
# CIRCUIT BREAKER
# =========================
class CircuitBreaker:
    def __init__(self, failure_threshold=Config.FAILURE_THRESHOLD, 
                 recovery_timeout=Config.RECOVERY_TIMEOUT):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time = 0
        self.state = "CLOSED"
        self.name = "BinanceAPI"
    
    def call(self, func, *args, **kwargs):
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                logger.info(f"{self.name}: Tentando recuperação (HALF_OPEN)")
                self.state = "HALF_OPEN"
            else:
                logger.warning(f"{self.name}: Circuit breaker OPEN - requisição bloqueada")
                raise Exception(f"Circuit breaker is OPEN for {self.name}")
        
        try:
            result = func(*args, **kwargs)
            if self.state == "HALF_OPEN":
                logger.info(f"{self.name}: Recuperado com sucesso (CLOSED)")
                self.state = "CLOSED"
                self.failures = 0
            return result
        except Exception as e:
            self.failures += 1
            self.last_failure_time = time.time()
            logger.error(f"{self.name}: Falha {self.failures}/{self.failure_threshold}: {e}")
            
            if self.failures >= self.failure_threshold:
                self.state = "OPEN"
                logger.error(f"{self.name}: Circuit breaker ABERTO após {self.failures} falhas")
            
            raise e
    
    def get_status(self):
        return {
            "state": self.state,
            "failures": self.failures,
            "last_failure": self.last_failure_time,
            "time_since_last_failure": time.time() - self.last_failure_time
        }

# =========================
# ALERT MANAGER
# =========================
class AlertManager:
    def __init__(self):
        self.alerts = defaultdict(list)
        self.triggered_alerts = deque(maxlen=100)
    
    def add_alert(self, symbol, condition_type, threshold, action="telegram"):
        alert_id = f"{symbol}_{condition_type}_{time.time()}"
        alert = {
            "id": alert_id,
            "symbol": symbol,
            "condition_type": condition_type,
            "threshold": threshold,
            "action": action,
            "created": datetime.now(),
            "triggered": False
        }
        self.alerts[symbol].append(alert)
        logger.info(f"Alerta adicionado: {symbol} - {condition_type} > {threshold}")
        return alert_id
    
    def check_alerts(self, symbol, indicators):
        triggered = []
        for alert in self.alerts.get(symbol, []):
            if alert["triggered"]:
                continue
                
            condition_met = False
            if alert["condition_type"] == "PRICE_ABOVE" and indicators["price"] > alert["threshold"]:
                condition_met = True
            elif alert["condition_type"] == "PRICE_BELOW" and indicators["price"] < alert["threshold"]:
                condition_met = True
            elif alert["condition_type"] == "RSI_ABOVE" and indicators.get("rsi", 50) > alert["threshold"]:
                condition_met = True
            elif alert["condition_type"] == "RSI_BELOW" and indicators.get("rsi", 50) < alert["threshold"]:
                condition_met = True
            elif alert["condition_type"] == "VOLUME_SPIKE" and indicators.get("volume", 0) > alert["threshold"]:
                condition_met = True
            
            if condition_met:
                alert["triggered"] = True
                alert["triggered_time"] = datetime.now()
                self.triggered_alerts.append(alert)
                triggered.append(alert)
                
                if alert["action"] == "telegram" and Config.TELEGRAM_TOKEN:
                    msg = f"🚨 ALERTA: {symbol}\n"
                    msg += f"Condição: {alert['condition_type']}\n"
                    msg += f"Valor: {alert['threshold']}\n"
                    msg += f"Preço atual: ${indicators['price']:.4f}\n"
                    msg += f"RSI: {indicators.get('rsi', 'N/A'):.1f}"
                    send_telegram(msg)
        
        return triggered

# =========================
# INICIALIZAÇÃO
# =========================
app = Flask(__name__)
binance_breaker = CircuitBreaker()
alert_manager = AlertManager()

signals_paused = False
last_signals = deque(maxlen=20)
performance_metrics = {
    "cache_hits": 0,
    "cache_misses": 0,
    "total_requests": 0,
    "analysis_times": deque(maxlen=100),
    "last_scan_time": None,
    "errors": deque(maxlen=100)
}

# =========================
# CACHE & HISTÓRICO
# =========================
indicator_history = {}
kline_cache = {}
cache_stats = defaultdict(int)

# =========================
# CONFIGURAÇÃO DO BOT
# =========================
TIMEFRAMES = ["1m", "5m", "15m"]

PAIRS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT",
    "DOGEUSDT", "DOTUSDT", "TRXUSDT", "LINKUSDT", "MATICUSDT", "LTCUSDT"
]

STRATEGIES = {
    "RSI_EXTREME": {"active": True, "weight": 1.2},
    "STOCH_FAST": {"active": True, "weight": 1.1},
    "PRICE_BREAKOUT": {"active": True, "weight": 1.4},
    "VOLUME_SPIKE": {"active": True, "weight": 1.3},
    "EMA_CROSS": {"active": True, "weight": 1.3},
    "MACD": {"active": True, "weight": 1.2},
}

# =========================
# FUNÇÕES UTILITÁRIAS
# =========================
def calculate_cache_hit_rate():
    total = performance_metrics["cache_hits"] + performance_metrics["cache_misses"]
    if total == 0:
        return 0
    return performance_metrics["cache_hits"] / total

def calculate_avg_analysis_time():
    times = list(performance_metrics["analysis_times"])
    if not times:
        return 0
    return sum(times) / len(times)

def calculate_timeframe_agreement(timeframe_signals):
    if len(timeframe_signals) < 2:
        return 0
    
    buy_votes = sum(1 for tf in timeframe_signals 
                   if any(s[0] == "COMPRA" for s in tf["signals"]))
    sell_votes = sum(1 for tf in timeframe_signals 
                    if any(s[0] == "VENDA" for s in tf["signals"]))
    
    total = len(timeframe_signals)
    return max(buy_votes, sell_votes) / total

# =========================
# BINANCE API COM CACHE E CIRCUIT BREAKER
# =========================
def get_binance_klines(symbol, interval="5m", limit=50):
    """Busca dados da Binance com cache simples"""
    key = f"{symbol}_{interval}"
    
    # Verificar cache (60 segundos)
    if key in kline_cache:
        data, timestamp = kline_cache[key]
        if time.time() - timestamp < 60:
            return data
    
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
        
        # ADICIONE ESTES HEADERS:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        }
        
        response = requests.get(
            url, 
            params=params, 
            timeout=15,  # Aumente timeout
            headers=headers  # Adicione headers
        )
        
        if response.status_code == 200:
            data = response.json()
            kline_cache[key] = (data, time.time())
            logger.info(f"✅ Dados obtidos: {symbol} {interval}")
            return data
        else:
            logger.error(f"❌ Erro HTTP {response.status_code} para {symbol}")
            
    except requests.exceptions.Timeout:
        logger.error(f"⏰ Timeout para {symbol}")
    except requests.exceptions.ConnectionError:
        logger.error(f"🔌 Erro de conexão para {symbol}")
    except Exception as e:
        logger.error(f"⚠️  Erro ao buscar {symbol}: {str(e)[:100]}")
    
    return None

# =========================
# INDICADORES
# =========================
def calculate_ema(prices, period):
    if len(prices) < period:
        return prices[-1] if prices else 0
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
    if len(prices) < 50:
        return None, None
    
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
        "timestamp": datetime.now()
    }
    prev = indicator_history.get((symbol, tf))
    indicator_history[(symbol, tf)] = ind
    
    # Verificar alertas
    alert_manager.check_alerts(symbol, ind)
    
    return ind, prev

# =========================
# ESTRATÉGIAS
# =========================
def apply_strategies(ind, prev):
    signals = []
    
    if STRATEGIES["RSI_EXTREME"]["active"]:
        if ind["rsi"] < 30:
            signals.append(("COMPRA", "RSI OVERSOLD", STRATEGIES["RSI_EXTREME"]["weight"]))
        elif ind["rsi"] > 70:
            signals.append(("VENDA", "RSI OVERBOUGHT", STRATEGIES["RSI_EXTREME"]["weight"]))
    
    if STRATEGIES["STOCH_FAST"]["active"]:
        if ind["stoch"] < 20:
            signals.append(("COMPRA", "STOCH OVERSOLD", STRATEGIES["STOCH_FAST"]["weight"]))
        elif ind["stoch"] > 80:
            signals.append(("VENDA", "STOCH OVERBOUGHT", STRATEGIES["STOCH_FAST"]["weight"]))
    
    if STRATEGIES["PRICE_BREAKOUT"]["active"]:
        if ind["price"] > ind["recent_high"]:
            signals.append(("COMPRA", "BREAKOUT ALTA", STRATEGIES["PRICE_BREAKOUT"]["weight"]))
        elif ind["price"] < ind["recent_low"]:
            signals.append(("VENDA", "BREAKDOWN BAIXA", STRATEGIES["PRICE_BREAKOUT"]["weight"]))
    
    if STRATEGIES["VOLUME_SPIKE"]["active"]:
        if ind["volume"] > ind["volume_avg"] * 3:
            direction = "COMPRA" if prev and ind["price"] > prev["price"] else "VENDA"
            signals.append((direction, "VOLUME SPIKE", STRATEGIES["VOLUME_SPIKE"]["weight"]))
    
    if STRATEGIES["EMA_CROSS"]["active"] and prev:
        if ind["ema9"] > ind["ema21"] and prev["ema9"] <= prev["ema21"]:
            signals.append(("COMPRA", "EMA GOLDEN CROSS", STRATEGIES["EMA_CROSS"]["weight"]))
        elif ind["ema9"] < ind["ema21"] and prev["ema9"] >= prev["ema21"]:
            signals.append(("VENDA", "EMA DEATH CROSS", STRATEGIES["EMA_CROSS"]["weight"]))
    
    if STRATEGIES["MACD"]["active"] and prev:
        macd = calculate_macd(ind["prices"])
        prev_macd = calculate_macd(prev["prices"])
        if macd > 0 and prev_macd <= 0:
            signals.append(("COMPRA", "MACD BULLISH", STRATEGIES["MACD"]["weight"]))
        elif macd < 0 and prev_macd >= 0:
            signals.append(("VENDA", "MACD BEARISH", STRATEGIES["MACD"]["weight"]))
    
    return signals

# =========================
# ANÁLISE MULTI-TIMEFRAME
# =========================
def analyze_symbol(symbol):
    start_time = time.time()
    
    try:
        buy_score = sell_score = 0
        reasons = []
        price = None
        used_tfs = []
        timeframe_signals = []
        
        for tf in TIMEFRAMES:
            klines = get_binance_klines(symbol, tf, limit=100)
            if not klines:
                continue
            
            closes = [float(k[4]) for k in klines]
            volumes = [float(k[5]) for k in klines]
            
            ind, prev = calculate_indicators(closes, volumes, symbol, tf)
            if ind is None:
                continue
                
            price = ind["price"]
            
            signals = apply_strategies(ind, prev)
            if signals:
                used_tfs.append(tf)
                timeframe_signals.append({
                    "timeframe": tf,
                    "signals": signals,
                    "indicators": ind
                })
                
                for direction, reason, weight in signals:
                    reasons.append(f"{tf}: {reason}")
                    if direction == "COMPRA":
                        buy_score += weight
                    else:
                        sell_score += weight
        
        if len(used_tfs) < 2:
            logger.debug(f"{symbol}: Dados insuficientes em {len(used_tfs)} TF(s)")
            return None
        
        # Verificar concordância entre timeframes
        if len(timeframe_signals) >= 2:
            agreement_score = calculate_timeframe_agreement(timeframe_signals)
            if agreement_score < 0.6:  # 60% de concordância mínima
                logger.info(f"{symbol}: Concordância baixa ({agreement_score:.0%}) - ignorando")
                return None
        
        logger.info(f"{symbol}: Dados OK em {len(used_tfs)} TFs ({', '.join(used_tfs)}). "
                    f"Buy_score: {buy_score:.1f} | Sell_score: {sell_score:.1f}")
        
        direction = "COMPRA" if buy_score > sell_score else "VENDA"
        score = max(buy_score, sell_score)
        confidence = min(score / (len(STRATEGIES) * 1.5), 1)  # Normalizar score
        
        if confidence < Config.MIN_CONFIDENCE:
            logger.debug(f"{symbol}: Confiança baixa ({confidence:.0%}) - ignorando")
            return None
        
        analysis_time = time.time() - start_time
        performance_metrics["analysis_times"].append(analysis_time)
        
        return {
            "symbol": symbol,
            "direction": direction,
            "price": price,
            "confidence": confidence,
            "score": score,
            "reasons": reasons[:3],
            "timeframes": used_tfs,
            "agreement_score": agreement_score if 'agreement_score' in locals() else 0,
            "timestamp": datetime.now(),
            "analysis_time": analysis_time
        }
        
    except Exception as e:
        logger.error(f"Erro analisando {symbol}: {e}")
        performance_metrics["errors"].append({
            "time": datetime.now(),
            "symbol": symbol,
            "error": str(e)
        })
        return None

# =========================
# TELEGRAM
# =========================
def send_telegram(msg):
    if not Config.TELEGRAM_TOKEN or not Config.CHAT_ID:
        logger.warning("Telegram não configurado (TOKEN ou CHAT_ID ausente)")
        return False
    
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{Config.TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": Config.CHAT_ID,
                "text": msg,
                "parse_mode": "Markdown"
            },
            timeout=10
        )
        response.raise_for_status()
        logger.info("Mensagem enviada para Telegram")
        return True
    except Exception as e:
        logger.error(f"Erro ao enviar Telegram: {e}")
        return False

def send_signal(signal):
    emoji = "🚀" if signal["direction"] == "COMPRA" else "🔻"
    msg = (
        f"{emoji} *{signal['direction']}*\n"
        f"Par: `{signal['symbol']}`\n"
        f"Preço: `${signal['price']:.4f}`\n"
        f"Confiança: {signal['confidence']:.0%}\n"
        f"Timeframes: {', '.join(signal['timeframes'])}\n"
        f"Razões:\n" + "\n".join(f"• {r}" for r in signal["reasons"])
    )
    
    if send_telegram(msg):
        last_signals.append(signal)
        return True
    return False

# =========================
# BACKTEST SIMPLES
# =========================
def backtest_strategy(symbol, days=7):
    """Backtest simples das estratégias"""
    logger.info(f"Iniciando backtest para {symbol} ({days} dias)")
    
    # Em produção, implementar histórico completo
    # Esta é uma versão simplificada
    
    test_results = {
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "total_return": 0,
        "max_drawdown": 0,
        "sharpe_ratio": 0
    }
    
    logger.info(f"Backtest concluído para {symbol}")
    return test_results

# =========================
# API ENDPOINTS
# =========================
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not Config.API_KEY:
            return f(*args, **kwargs)
        
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        if api_key and api_key == Config.API_KEY:
            return f(*args, **kwargs)
        return jsonify({"error": "Unauthorized"}), 401
    return decorated_function

@app.route("/")
def dashboard():
    if not Config.ENABLE_WEB:
        return jsonify({"status": "Web interface disabled"})
    
    strategies_html = "".join(
        f'<span class="px-3 py-1 rounded-full text-xs font-bold {"bg-green-600" if v["active"] else "bg-red-600"}">'
        f'{k.replace("_", " ")} (w:{v["weight"]})</span>'
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
                    <th class="px-4 py-3 text-left">TF</th>
                    <th class="px-4 py-3 text-right">Horário</th>
                </tr>
            </thead>
            <tbody>
        """
        for s in reversed(list(last_signals)[-10:]):
            emoji = "🟢" if s["direction"] == "COMPRA" else "🔴"
            color = "text-green-400" if s["direction"] == "COMPRA" else "text-red-400"
            time_str = s["timestamp"].strftime("%H:%M:%S")
            tfs = ", ".join(s.get("timeframes", []))
            signals_table += f"""
                <tr class="border-b border-gray-700 hover:bg-gray-800 transition">
                    <td class="px-4 py-3 {color} font-bold">{emoji} {s['direction']}</td>
                    <td class="px-4 py-3 font-mono">{s['symbol']}</td>
                    <td class="px-4 py-3 text-right font-mono">${s['price']:,.4f}</td>
                    <td class="px-4 py-3 text-right">{int(s['confidence']*100)}%</td>
                    <td class="px-4 py-3 text-sm text-gray-400">{tfs}</td>
                    <td class="px-4 py-3 text-right text-xs text-gray-500">{time_str}</td>
                </tr>
            """
        signals_table += "</tbody></table>"
    else:
        signals_table = '<p class="text-gray-400 text-center py-8">Aguardando primeiros sinais...</p>'
    
    # Circuit breaker status
    cb_status = binance_breaker.get_status()
    cb_state_color = {
        "CLOSED": "text-green-400",
        "OPEN": "text-red-400",
        "HALF_OPEN": "text-yellow-400"
    }.get(cb_status["state"], "text-gray-400")
    
    # Cache stats
    hit_rate = calculate_cache_hit_rate() * 100
    
    return f"""
    <!DOCTYPE html>
    <html lang="pt-BR" class="bg-gray-900 text-gray-100">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>🤖 Bot Sinais Cripto Pro</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css" rel="stylesheet">
        <style>
            body {{ font-family: 'Segoe UI', sans-serif; }}
            .blink {{ animation: blink 1s infinite; }}
            @keyframes blink {{ 50% {{ opacity: 0.5; }} }}
            .progress-bar {{ 
                width: 100%; 
                height: 8px; 
                background: #374151; 
                border-radius: 4px;
                overflow: hidden;
            }}
            .progress-fill {{ 
                height: 100%; 
                background: linear-gradient(90deg, #3B82F6, #8B5CF6);
                transition: width 0.5s ease;
            }}
        </style>
    </head>
    <body class="min-h-screen">
        <div class="container mx-auto p-6 max-w-6xl">
            <div class="text-center mb-10">
                <h1 class="text-5xl font-bold mb-4 bg-gradient-to-r from-blue-500 to-purple-600 bg-clip-text text-transparent">
                    🤖 Bot de Sinais Cripto Pro
                </h1>
                <p class="text-2xl flex items-center justify-center gap-3">
                    Status: <span class="text-green-400 blink">● ONLINE</span>
                    <span id="countdown" class="text-yellow-400 font-mono">{Config.BOT_INTERVAL}s até próxima scan</span>
                </p>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-10">
                <div class="bg-gray-800 rounded-2xl p-6 border border-gray-700">
                    <h3 class="text-lg text-gray-400 mb-2">Pares Monitorados</h3>
                    <p class="text-3xl font-bold">{len(PAIRS)}</p>
                    <div class="progress-bar mt-2">
                        <div class="progress-fill" style="width: {min(len(PAIRS)/20*100, 100)}%"></div>
                    </div>
                </div>
                <div class="bg-gray-800 rounded-2xl p-6 border border-gray-700">
                    <h3 class="text-lg text-gray-400 mb-2">Cache Hit Rate</h3>
                    <p class="text-3xl font-bold">{hit_rate:.1f}%</p>
                    <p class="text-sm text-gray-500 mt-2">{performance_metrics['cache_hits']} hits / {performance_metrics['cache_misses']} misses</p>
                </div>
                <div class="bg-gray-800 rounded-2xl p-6 border border-gray-700">
                    <h3 class="text-lg text-gray-400 mb-2">Circuit Breaker</h3>
                    <p class="text-3xl font-bold {cb_state_color}">{cb_status["state"]}</p>
                    <p class="text-sm text-gray-500 mt-2">Falhas: {cb_status["failures"]}</p>
                </div>
                <div class="bg-gray-800 rounded-2xl p-6 border border-gray-700">
                    <h3 class="text-lg text-gray-400 mb-2">Performance</h3>
                    <p class="text-3xl font-bold">{calculate_avg_analysis_time()*1000:.0f}ms</p>
                    <p class="text-sm text-gray-500 mt-2">Análise média por par</p>
                </div>
            </div>

            <div class="bg-gray-800 rounded-2xl p-6 mb-10 border border-gray-700">
                <h2 class="text-2xl font-bold mb-4 flex items-center gap-3">
                    <i class="fas fa-brain text-purple-500"></i> Estratégias Ativas
                </h2>
                <div class="flex flex-wrap gap-3">
                    {strategies_html}
                </div>
                <div class="mt-4 text-sm text-gray-400">
                    <i class="fas fa-info-circle"></i> w = peso da estratégia
                </div>
            </div>

            <div class="bg-gray-800 rounded-2xl p-6 border border-gray-700 mb-10">
                <h2 class="text-2xl font-bold mb-6 flex items-center gap-3">
                    <i class="fas fa-bolt text-yellow-500"></i> Últimos Sinais Gerados
                </h2>
                <div class="overflow-x-auto">
                    {signals_table}
                </div>
            </div>

            <div class="text-center mt-12 text-gray-500 text-sm">
                Bot rodando desde {datetime.now().strftime("%d/%m/%Y %H:%M")} • 
                Varredura a cada {Config.BOT_INTERVAL}s • 
                v2.0 • 
                <a href="/health" class="text-blue-400 hover:text-blue-300">Health Check</a> •
                <a href="/metrics" class="text-blue-400 hover:text-blue-300">Metrics</a>
            </div>
        </div>

        <script>
            let seconds = {Config.BOT_INTERVAL};
            const countdownEl = document.getElementById('countdown');
            
            setInterval(() => {{
                seconds = seconds <= 0 ? {Config.BOT_INTERVAL} : seconds - 1;
                countdownEl.innerText = seconds + 's até próxima scan';
            }}, 1000);
            
            // Auto-refresh a cada 30 segundos
            setInterval(() => {{
                window.location.reload();
            }}, 30000);
        </script>
    </body>
    </html>
    """

@app.route("/health")
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "signals_generated": len(last_signals),
        "memory_usage": psutil.Process().memory_percent(),
        "cache_size": len(kline_cache),
        "circuit_breaker": binance_breaker.get_status(),
        "uptime": time.time() - performance_metrics.get("start_time", time.time())
    })

@app.route("/metrics")
@require_api_key
def metrics():
    return jsonify({
        "pairs_monitored": len(PAIRS),
        "active_strategies": sum(1 for s in STRATEGIES.values() if s["active"]),
        "cache_stats": {
            "hits": performance_metrics["cache_hits"],
            "misses": performance_metrics["cache_misses"],
            "hit_rate": calculate_cache_hit_rate(),
            "size": len(kline_cache)
        },
        "performance": {
            "avg_analysis_time": calculate_avg_analysis_time(),
            "last_scan_time": performance_metrics["last_scan_time"],
            "total_requests": performance_metrics["total_requests"]
        },
        "signals": {
            "total": len(last_signals),
            "last_10": list(last_signals)[-10:] if last_signals else []
        },
        "errors_last_24h": len([e for e in performance_metrics["errors"] 
                               if datetime.now() - e["time"] < timedelta(hours=24)])
    })

@app.route("/api/signals")
@require_api_key
def api_signals():
    return jsonify({
        "signals": list(last_signals),
        "count": len(last_signals),
        "timestamp": datetime.now().isoformat()
    })

@app.route("/api/analyze/<symbol>")
@require_api_key
def api_analyze(symbol):
    signal = analyze_symbol(symbol)
    return jsonify(signal or {"error": "No signal generated"})

@app.route("/api/strategies", methods=["GET", "POST"])
@require_api_key
def api_strategies():
    if request.method == "POST":
        data = request.json
        for strategy, config in data.items():
            if strategy in STRATEGIES:
                STRATEGIES[strategy].update(config)
        return jsonify({"status": "updated", "strategies": STRATEGIES})
    return jsonify(STRATEGIES)

@app.route("/api/alerts", methods=["GET", "POST"])
@require_api_key
def api_alerts():
    if request.method == "POST":
        data = request.json
        alert_id = alert_manager.add_alert(
            data["symbol"],
            data["condition_type"],
            data["threshold"],
            data.get("action", "telegram")
        )
        return jsonify({"status": "created", "alert_id": alert_id})
    
    return jsonify({
        "active_alerts": sum(len(alerts) for alerts in alert_manager.alerts.values()),
        "triggered_alerts": list(alert_manager.triggered_alerts)[-10:]
    })

# =========================
# LOOP PRINCIPAL (PARALELO)
# =========================
def run_bot():
    performance_metrics["start_time"] = time.time()
    logger.info("🤖 BOT INICIADO - Varredura paralela")
    
    while True:
        try:
            scan_start = time.time()
            logger.info("=== NOVA VARREDURA INICIADA ===")
            
            signals_generated = 0
            with ThreadPoolExecutor(max_workers=Config.MAX_WORKERS) as executor:
                future_to_symbol = {
                    executor.submit(analyze_symbol, symbol): symbol 
                    for symbol in PAIRS
                }
                
                for future in as_completed(future_to_symbol):
                    symbol = future_to_symbol[future]
                    try:
                        signal = future.result(timeout=30)
                        if signal:
                            logger.info(f"SINAL GERADO: {signal['direction']} {symbol} - Confiança {signal['confidence']:.0%}")
                            if send_signal(signal):
                                signals_generated += 1
                    except Exception as e:
                        logger.error(f"Erro analisando {symbol}: {e}")
            
            scan_time = time.time() - scan_start
            performance_metrics["last_scan_time"] = datetime.now().isoformat()
            
            logger.info(f"Varredura concluída em {scan_time:.1f}s. Sinais: {signals_generated}. Dormindo {Config.BOT_INTERVAL}s...")
            time.sleep(Config.BOT_INTERVAL)
            
        except Exception as e:
            logger.error(f"Erro no loop principal: {e}")
            time.sleep(10)

# =========================
# MAIN
# =========================
def main():
    logger.info(f"🚀 Iniciando Bot de Sinais Cripto Pro v2.0")
    logger.info(f"📊 Pares: {len(PAIRS)} | Estratégias: {sum(1 for s in STRATEGIES.values() if s['active'])}")
    logger.info(f"⚙️ Config: Interval={Config.BOT_INTERVAL}s, Confidence={Config.MIN_CONFIDENCE}")
    
    if Config.TELEGRAM_TOKEN and Config.CHAT_ID:
        logger.info("✅ Telegram configurado")
        send_telegram(f"🤖 Bot iniciado em {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    else:
        logger.warning("⚠️ Telegram não configurado")
    
    # Adicionar alguns alertas de exemplo
    alert_manager.add_alert("BTCUSDT", "PRICE_ABOVE", 45000)
    alert_manager.add_alert("BTCUSDT", "RSI_BELOW", 30)
    
    # Iniciar bot em thread separada
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Iniciar servidor web
    if Config.ENABLE_WEB:
        logger.info(f"🌐 Dashboard disponível em http://0.0.0.0:10000")
        app.run(host="0.0.0.0", port=10000, debug=False)
    else:
        logger.info("🌐 Web interface desabilitada")
        bot_thread.join()

if __name__ == "__main__":
    main()
