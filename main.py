import os
import time
import threading
import requests
import logging
from datetime import datetime, timedelta
from flask import Flask, jsonify
from dotenv import load_dotenv
from collections import deque, defaultdict
import json

# =========================
# CONFIGURAÇÃO
# =========================
load_dotenv()

# Configurações
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
BOT_INTERVAL = int(os.getenv("BOT_INTERVAL", 600))  # 10 minutos para cloud
PORT = int(os.getenv("PORT", 10000))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# =========================
# SETUP
# =========================
app = Flask(__name__)

# Variáveis globais
last_signals = deque(maxlen=15)
kline_cache = {}
circuit_state = "CLOSED"
circuit_failures = 0
last_failure_time = 0
performance_stats = {
    "requests_total": 0,
    "requests_success": 0,
    "requests_failed": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "last_scan": None
}

# Configurar logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =========================
# CONFIGURAÇÃO DO BOT (OTIMIZADA PARA CLOUD)
# =========================
TIMEFRAMES = ["15m", "30m"]  # Timeframes maiores para menos requests
PAIRS = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]  # Apenas 3 pares principais

# Estratégias simplificadas
STRATEGIES = {
    "RSI": {"active": True, "weight": 1.5},
    "PRICE_ACTION": {"active": True, "weight": 1.3},
    "TREND": {"active": True, "weight": 1.2},
}

# =========================
# CIRCUIT BREAKER SIMPLIFICADO
# =========================
def check_circuit_breaker():
    """Verifica se podemos fazer requests"""
    global circuit_state, circuit_failures, last_failure_time
    
    if circuit_state == "OPEN":
        # Verificar se já passou tempo suficiente para tentar recuperação
        if time.time() - last_failure_time > 300:  # 5 minutos
            circuit_state = "HALF_OPEN"
            circuit_failures = 0
            logger.info("🔄 Circuit breaker em modo HALF_OPEN (tentando recuperação)")
            return True
        return False
    
    return True

def update_circuit_breaker(success):
    """Atualiza estado do circuit breaker"""
    global circuit_state, circuit_failures, last_failure_time
    
    if success:
        if circuit_state == "HALF_OPEN":
            circuit_state = "CLOSED"
            circuit_failures = 0
            logger.info("✅ Circuit breaker recuperado (CLOSED)")
    else:
        circuit_failures += 1
        last_failure_time = time.time()
        
        if circuit_failures >= 5:  # 5 falhas consecutivas
            circuit_state = "OPEN"
            logger.error(f"🔴 Circuit breaker ABERTO após {circuit_failures} falhas")

# =========================
# FUNÇÕES DE API
# =========================
def get_binance_klines(symbol, interval="15m", limit=30):
    """Busca dados da Binance com proteção e cache"""
    
    # Verificar circuit breaker
    if not check_circuit_breaker():
        logger.warning(f"⏸️ Circuit breaker OPEN - pulando {symbol}")
        return None
    
    key = f"{symbol}_{interval}"
    
    # Verificar cache (90 segundos)
    if key in kline_cache:
        data, timestamp = kline_cache[key]
        if time.time() - timestamp < 90:
            performance_stats["cache_hits"] += 1
            return data
    
    performance_stats["cache_misses"] += 1
    performance_stats["requests_total"] += 1
    
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": limit
        }
        
        # Headers para evitar bloqueio
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        
        logger.debug(f"📡 Request: {symbol} {interval}")
        response = requests.get(
            url, 
            params=params, 
            headers=headers,
            timeout=15
        )
        
        if response.status_code == 200:
            data = response.json()
            
            # Validar dados
            if len(data) > 0:
                kline_cache[key] = (data, time.time())
                performance_stats["requests_success"] += 1
                update_circuit_breaker(True)
                logger.debug(f"✅ Dados recebidos: {symbol} ({len(data)} candles)")
                return data
            else:
                logger.warning(f"⚠️ Dados vazios para {symbol}")
                performance_stats["requests_failed"] += 1
                update_circuit_breaker(False)
                return None
                
        elif response.status_code == 429:  # Too Many Requests
            logger.error(f"⏰ Rate limit excedido para {symbol}")
            circuit_state = "OPEN"
            last_failure_time = time.time()
            return None
            
        else:
            logger.error(f"❌ HTTP {response.status_code} para {symbol}")
            performance_stats["requests_failed"] += 1
            update_circuit_breaker(False)
            return None
            
    except requests.exceptions.Timeout:
        logger.error(f"⏰ Timeout para {symbol}")
        performance_stats["requests_failed"] += 1
        update_circuit_breaker(False)
        return None
        
    except requests.exceptions.ConnectionError:
        logger.error(f"🔌 Connection error para {symbol}")
        performance_stats["requests_failed"] += 1
        update_circuit_breaker(False)
        return None
        
    except Exception as e:
        logger.error(f"⚠️ Erro desconhecido para {symbol}: {str(e)[:100]}")
        performance_stats["requests_failed"] += 1
        update_circuit_breaker(False)
        return None

# =========================
# INDICADORES SIMPLIFICADOS
# =========================
def calculate_rsi(prices, period=14):
    """Calcula RSI"""
    if len(prices) < period + 1:
        return 50
    
    gains = []
    losses = []
    
    for i in range(1, period + 1):
        change = prices[-i] - prices[-i-1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0
    
    if avg_loss == 0:
        return 100 if avg_gain > 0 else 50
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)

def calculate_sma(prices, period=20):
    """Calcula Simple Moving Average"""
    if len(prices) < period:
        return prices[-1] if prices else 0
    return sum(prices[-period:]) / period

def calculate_support_resistance(prices):
    """Identifica suporte e resistência simples"""
    if len(prices) < 20:
        return prices[-1], prices[-1]
    
    recent = prices[-20:]
    support = min(recent)
    resistance = max(recent)
    return support, resistance

# =========================
# ANÁLISE
# =========================
def analyze_symbol(symbol):
    """Analisa um símbolo"""
    try:
        signals = []
        current_price = None
        analysis_data = {}
        
        for tf in TIMEFRAMES:
            # Buscar dados
            klines = get_binance_klines(symbol, tf, 30)
            if not klines or len(klines) < 15:
                continue
            
            # Processar dados
            closes = [float(k[4]) for k in klines]
            highs = [float(k[2]) for k in klines]
            lows = [float(k[3]) for k in klines]
            
            current_price = closes[-1]
            analysis_data[tf] = {
                "price": current_price,
                "high": highs[-1],
                "low": lows[-1]
            }
            
            # Calcular indicadores
            rsi = calculate_rsi(closes)
            sma_20 = calculate_sma(closes, 20)
            support, resistance = calculate_support_resistance(closes)
            
            # Aplicar estratégias
            if STRATEGIES["RSI"]["active"]:
                if rsi < 32:
                    signals.append(("COMPRA", f"RSI {rsi} (sobrevenda)", STRATEGIES["RSI"]["weight"]))
                elif rsi > 68:
                    signals.append(("VENDA", f"RSI {rsi} (sobrecompra)", STRATEGIES["RSI"]["weight"]))
            
            if STRATEGIES["PRICE_ACTION"]["active"]:
                if current_price < support * 1.01:  # Próximo do suporte
                    signals.append(("COMPRA", f"Próximo suporte ${support:.2f}", STRATEGIES["PRICE_ACTION"]["weight"]))
                elif current_price > resistance * 0.99:  # Próximo da resistência
                    signals.append(("VENDA", f"Próximo resistência ${resistance:.2f}", STRATEGIES["PRICE_ACTION"]["weight"]))
            
            if STRATEGIES["TREND"]["active"] and len(closes) >= 20:
                sma_10 = calculate_sma(closes, 10)
                if sma_10 > sma_20 and closes[-1] > sma_10:
                    signals.append(("COMPRA", f"Tendência alta (SMA10 > SMA20)", STRATEGIES["TREND"]["weight"]))
                elif sma_10 < sma_20 and closes[-1] < sma_10:
                    signals.append(("VENDA", f"Tendência baixa (SMA10 < SMA20)", STRATEGIES["TREND"]["weight"]))
        
        if not signals or current_price is None:
            return None
        
        # Agregar sinais
        buy_score = sum(w for d, r, w in signals if d == "COMPRA")
        sell_score = sum(w for d, r, w in signals if d == "VENDA")
        
        if buy_score == 0 and sell_score == 0:
            return None
        
        # Determinar direção
        direction = "COMPRA" if buy_score > sell_score else "VENDA"
        score = max(buy_score, sell_score)
        
        # Calcular confiança (0-100%)
        max_possible_score = sum(s["weight"] for s in STRATEGIES.values() if s["active"]) * len(TIMEFRAMES)
        confidence = min(score / max_possible_score, 1.0)
        
        # Filtrar por confiança mínima
        if confidence < 0.5:  # 50% mínimo
            return None
        
        # Coletar razões
        reasons = [r for d, r, w in signals if d == direction][:3]
        
        signal_data = {
            "symbol": symbol,
            "direction": direction,
            "price": round(current_price, 4),
            "confidence": round(confidence, 2),
            "score": round(score, 1),
            "reasons": reasons,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "date": datetime.now().strftime("%d/%m/%Y"),
            "analysis_data": analysis_data
        }
        
        logger.info(f"📊 Sinal: {direction} {symbol} ${current_price:.2f} ({confidence:.0%})")
        return signal_data
        
    except Exception as e:
        logger.error(f"❌ Erro analisando {symbol}: {e}")
        return None

# =========================
# TELEGRAM
# =========================
def send_telegram(message):
    """Envia mensagem para o Telegram"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.warning("⚠️ Telegram não configurado")
        return False
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
        
        response = requests.post(url, json=data, timeout=10)
        if response.status_code == 200:
            logger.debug("✅ Mensagem enviada para Telegram")
            return True
        else:
            logger.error(f"❌ Erro Telegram: {response.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Falha ao enviar Telegram: {e}")
        return False

def send_signal(signal):
    """Processa e envia um sinal"""
    emoji = "🚀" if signal["direction"] == "COMPRA" else "🔻"
    direction_emoji = "🟢" if signal["direction"] == "COMPRA" else "🔴"
    
    message = (
        f"{direction_emoji} *{signal['direction']} {signal['symbol']}*\n"
        f"{emoji} *Preço:* `${signal['price']:,}`\n"
        f"📊 *Confiança:* {int(signal['confidence'] * 100)}%\n"
        f"🏆 *Score:* {signal['score']}/10\n"
        f"⏰ *Horário:* {signal['timestamp']}\n"
        f"📅 *Data:* {signal['date']}\n\n"
        f"*Motivos:*\n"
    )
    
    for i, reason in enumerate(signal["reasons"], 1):
        message += f"  {i}. {reason}\n"
    
    message += f"\n#CryptoBot #{signal['symbol'].replace('USDT', '')}"
    
    if send_telegram(message):
        last_signals.append(signal)
        return True
    return False

# =========================
# ROTAS WEB
# =========================
@app.route('/')
def dashboard():
    """Dashboard principal"""
    # Estatísticas
    cache_hit_rate = 0
    if performance_stats["cache_hits"] + performance_stats["cache_misses"] > 0:
        cache_hit_rate = (performance_stats["cache_hits"] / 
                         (performance_stats["cache_hits"] + performance_stats["cache_misses"])) * 100
    
    success_rate = 0
    if performance_stats["requests_total"] > 0:
        success_rate = (performance_stats["requests_success"] / 
                       performance_stats["requests_total"]) * 100
    
    # Sinais recentes
    signals_html = ""
    for signal in list(last_signals)[-10:]:
        color_class = "signal-buy" if signal["direction"] == "COMPRA" else "signal-sell"
        time_ago = ""
        try:
            signal_time = datetime.strptime(f"{signal['date']} {signal['timestamp']}", "%d/%m/%Y %H:%M:%S")
            time_diff = datetime.now() - signal_time
            if time_diff.total_seconds() < 3600:
                time_ago = f"{int(time_diff.total_seconds() / 60)} min atrás"
            elif time_diff.total_seconds() < 86400:
                time_ago = f"{int(time_diff.total_seconds() / 3600)}h atrás"
            else:
                time_ago = signal['timestamp']
        except:
            time_ago = signal['timestamp']
        
        signals_html += f"""
        <div class="signal {color_class}">
            <div class="signal-header">
                <span class="signal-direction">{signal['direction']}</span>
                <span class="signal-symbol">{signal['symbol']}</span>
                <span class="signal-price">${signal['price']:,.2f}</span>
            </div>
            <div class="signal-body">
                <div class="signal-confidence">Confiança: {int(signal['confidence']*100)}%</div>
                <div class="signal-reasons">{' • '.join(signal['reasons'][:2])}</div>
                <div class="signal-time">{time_ago}</div>
            </div>
        </div>
        """
    
    if not signals_html:
        signals_html = '<div class="no-signals">⏳ Aguardando primeiros sinais...</div>'
    
    # Estratégias ativas
    strategies_html = ""
    for name, config in STRATEGIES.items():
        status_class = "strategy-active" if config["active"] else "strategy-inactive"
        strategies_html += f'<span class="strategy {status_class}">{name} (w:{config["weight"]})</span>'
    
    return f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Crypto Trading Bot Pro</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ 
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: #333;
                min-height: 100vh;
                padding: 20px;
            }}
            .container {{ 
                max-width: 1200px; 
                margin: 0 auto;
                background: white;
                border-radius: 20px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                overflow: hidden;
            }}
            .header {{ 
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                color: white;
                padding: 40px;
                text-align: center;
                border-bottom: 5px solid #00d4ff;
            }}
            .header h1 {{ 
                font-size: 2.5em; 
                margin-bottom: 10px;
                background: linear-gradient(90deg, #00d4ff, #ff00cc);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }}
            .header p {{ 
                font-size: 1.2em; 
                opacity: 0.9;
                margin-bottom: 20px;
            }}
            .status {{ 
                display: inline-flex;
                align-items: center;
                background: rgba(0, 212, 255, 0.1);
                padding: 10px 20px;
                border-radius: 50px;
                font-weight: bold;
            }}
            .status.online {{ color: #00ff88; }}
            .status.blink {{ 
                animation: blink 1s infinite;
            }}
            @keyframes blink {{
                0%, 100% {{ opacity: 1; }}
                50% {{ opacity: 0.5; }}
            }}
            .stats-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                gap: 20px;
                padding: 30px;
                background: #f8f9fa;
            }}
            .stat-card {{
                background: white;
                padding: 25px;
                border-radius: 15px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.08);
                text-align: center;
                transition: transform 0.3s;
            }}
            .stat-card:hover {{
                transform: translateY(-5px);
            }}
            .stat-card h3 {{
                font-size: 2.5em;
                color: #667eea;
                margin-bottom: 10px;
            }}
            .stat-card p {{
                color: #666;
                font-size: 0.9em;
            }}
            .circuit-open {{ color: #ff4757; }}
            .circuit-closed {{ color: #2ed573; }}
            .circuit-half {{ color: #ffa502; }}
            .section {{
                padding: 30px;
                border-bottom: 1px solid #eee;
            }}
            .section-title {{
                font-size: 1.5em;
                color: #333;
                margin-bottom: 20px;
                display: flex;
                align-items: center;
                gap: 10px;
            }}
            .strategies {{
                display: flex;
                flex-wrap: wrap;
                gap: 10px;
            }}
            .strategy {{
                padding: 8px 16px;
                border-radius: 20px;
                font-size: 0.9em;
                font-weight: 600;
            }}
            .strategy-active {{
                background: #d4edda;
                color: #155724;
                border: 2px solid #c3e6cb;
            }}
            .strategy-inactive {{
                background: #f8d7da;
                color: #721c24;
                border: 2px solid #f5c6cb;
            }}
            .signals-container {{
                max-height: 500px;
                overflow-y: auto;
                padding-right: 10px;
            }}
            .signal {{
                background: white;
                border-radius: 12px;
                padding: 20px;
                margin-bottom: 15px;
                box-shadow: 0 3px 10px rgba(0,0,0,0.08);
                border-left: 5px solid;
                transition: all 0.3s;
            }}
            .signal:hover {{
                box-shadow: 0 5px 20px rgba(0,0,0,0.15);
            }}
            .signal-buy {{ border-color: #00d4ff; }}
            .signal-sell {{ border-color: #ff4757; }}
            .signal-header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 10px;
            }}
            .signal-direction {{
                font-weight: bold;
                font-size: 1.2em;
            }}
            .signal-symbol {{
                font-family: monospace;
                font-size: 1.1em;
                color: #555;
            }}
            .signal-price {{
                font-weight: bold;
                color: #333;
            }}
            .signal-confidence {{
                color: #667eea;
                font-weight: 600;
                margin-bottom: 5px;
            }}
            .signal-reasons {{
                color: #666;
                font-size: 0.95em;
                margin-bottom: 5px;
            }}
            .signal-time {{
                color: #999;
                font-size: 0.85em;
            }}
            .no-signals {{
                text-align: center;
                padding: 40px;
                color: #999;
                font-size: 1.1em;
            }}
            .footer {{
                text-align: center;
                padding: 20px;
                color: #666;
                font-size: 0.9em;
                background: #f8f9fa;
            }}
            .countdown {{
                font-family: monospace;
                background: #1a1a2e;
                color: #00ff88;
                padding: 5px 10px;
                border-radius: 5px;
                margin-left: 10px;
            }}
            .controls {{
                display: flex;
                gap: 10px;
                margin-top: 20px;
            }}
            .btn {{
                padding: 10px 20px;
                border: none;
                border-radius: 8px;
                cursor: pointer;
                font-weight: 600;
                transition: all 0.3s;
            }}
            .btn-primary {{
                background: #667eea;
                color: white;
            }}
            .btn-primary:hover {{
                background: #5a67d8;
            }}
            .btn-danger {{
                background: #ff4757;
                color: white;
            }}
            .btn-danger:hover {{
                background: #ff3742;
            }}
            .btn-success {{
                background: #2ed573;
                color: white;
            }}
            .btn-success:hover {{
                background: #25c464;
            }}
            @media (max-width: 768px) {{
                .stats-grid {{
                    grid-template-columns: 1fr;
                }}
                .header h1 {{
                    font-size: 2em;
                }}
                .signal-header {{
                    flex-direction: column;
                    align-items: flex-start;
                    gap: 5px;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🤖 Crypto Trading Bot Pro</h1>
                <p>Monitoramento inteligente de criptomoedas em tempo real</p>
                <div class="status online blink">
                    <span>● ONLINE</span>
                    <span class="countdown" id="countdown">{BOT_INTERVAL}s</span>
                </div>
                
                <div class="controls">
                    <button class="btn btn-primary" onclick="window.location.href='/health'">Health Check</button>
                    <button class="btn btn-success" onclick="window.location.href='/stats'">Estatísticas</button>
                    <button class="btn btn-danger" onclick="window.location.href='/reset'">Reset Cache</button>
                </div>
            </div>
            
            <div class="stats-grid">
                <div class="stat-card">
                    <h3>{len(PAIRS)}</h3>
                    <p>Pares Monitorados</p>
                    <small>{', '.join(PAIRS)}</small>
                </div>
                
                <div class="stat-card">
                    <h3>{cache_hit_rate:.1f}%</h3>
                    <p>Cache Hit Rate</p>
                    <small>{performance_stats['cache_hits']} hits / {performance_stats['cache_misses']} misses</small>
                </div>
                
                <div class="stat-card">
                    <h3 class="circuit-{circuit_state.lower()}">{circuit_state}</h3>
                    <p>Circuit Breaker</p>
                    <small>Falhas: {circuit_failures} | Status: {circuit_state}</small>
                </div>
                
                <div class="stat-card">
                    <h3>{success_rate:.1f}%</h3>
                    <p>Taxa de Sucesso API</p>
                    <small>{performance_stats['requests_success']} ok / {performance_stats['requests_failed']} falhas</small>
                </div>
            </div>
            
            <div class="section">
                <div class="section-title">
                    <span>🎯 Estratégias Ativas</span>
                </div>
                <div class="strategies">
                    {strategies_html}
                </div>
                <p style="margin-top: 10px; color: #666; font-size: 0.9em;">
                    <strong>Legenda:</strong> w = peso da estratégia | ● = ativa | ○ = inativa
                </p>
            </div>
            
            <div class="section">
                <div class="section-title">
                    <span>📈 Últimos Sinais Gerados</span>
                </div>
                <div class="signals-container">
                    {signals_html}
                </div>
            </div>
            
            <div class="footer">
                <p>
                    Bot rodando desde {datetime.now().strftime("%d/%m/%Y %H:%M")} • 
                    Varredura a cada {BOT_INTERVAL}s • 
                    v2.0 • 
                    <a href="/health" style="color: #667eea;">Health</a> • 
                    <a href="/api/signals" style="color: #667eea;">API</a>
                </p>
                <p style="margin-top: 10px; font-size: 0.8em; color: #999;">
                    ⚠️ Este é um bot de análise. Não constitui recomendação de investimento.
                </p>
            </div>
        </div>
        
        <script>
            // Countdown timer
            let seconds = {BOT_INTERVAL};
            const countdownEl = document.getElementById('countdown');
            
            setInterval(() => {{
                seconds = seconds <= 0 ? {BOT_INTERVAL} : seconds - 1;
                countdownEl.textContent = seconds + 's';
            }}, 1000);
            
            // Auto-refresh a cada 60 segundos
            setTimeout(() => {{
                window.location.reload();
            }}, 60000);
            
            // Smooth scroll para sinais
            document.querySelectorAll('.signal').forEach(signal => {{
                signal.addEventListener('click', () => {{
                    signal.style.transform = 'scale(0.98)';
                    setTimeout(() => signal.style.transform = '', 150);
                }});
            }});
        </script>
    </body>
    </html>
    """

@app.route('/health')
def health():
    """Health check para Render"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "crypto-trading-bot",
        "version": "2.0",
        "uptime_seconds": int(time.time() - performance_stats.get("start_time", time.time())),
        "memory_usage": "N/A",  # psutil não disponível em todas instâncias
        "signals_count": len(last_signals),
        "circuit_breaker": {
            "state": circuit_state,
            "failures": circuit_failures,
            "last_failure": last_failure_time
        },
        "performance": {
            "cache_hit_rate": f"{(performance_stats['cache_hits'] / (performance_stats['cache_hits'] + performance_stats['cache_misses'] + 0.001)) * 100:.1f}%",
            "api_success_rate": f"{(performance_stats['requests_success'] / (performance_stats['requests_total'] + 0.001)) * 100:.1f}%",
            "last_scan": performance_stats["last_scan"]
        }
    })

@app.route('/stats')
def stats():
    """Página de estatísticas detalhadas"""
    return jsonify({
        "performance": performance_stats,
        "configuration": {
            "pairs": PAIRS,
            "timeframes": TIMEFRAMES,
            "interval_seconds": BOT_INTERVAL,
            "strategies": STRATEGIES
        },
        "circuit_breaker": {
            "state": circuit_state,
            "failures": circuit_failures,
            "last_failure": last_failure_time,
            "is_open": circuit_state == "OPEN"
        },
        "signals": {
            "total_generated": len(last_signals),
            "last_10": list(last_signals)[-10:]
        }
    })

@app.route('/reset')
def reset():
    """Resetar cache e circuit breaker"""
    global kline_cache, circuit_state, circuit_failures, last_failure_time
    
    kline_cache.clear()
    circuit_state = "CLOSED"
    circuit_failures = 0
    last_failure_time = 0
    
    logger.info("🔄 Cache e circuit breaker resetados")
    return jsonify({
        "status": "reset",
        "message": "Cache e circuit breaker resetados com sucesso",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/signals')
def api_signals():
    """API para obter sinais"""
    return jsonify({
        "count": len(last_signals),
        "signals": list(last_signals),
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/analyze/<symbol>')
def api_analyze(symbol):
    """API para analisar um símbolo específico"""
    signal = analyze_symbol(symbol.upper())
    return jsonify(signal if signal else {"error": "Nenhum sinal gerado"})

# =========================
# LOOP DO BOT
# =========================
def run_bot():
    """Loop principal do bot"""
    performance_stats["start_time"] = time.time()
    logger.info("=" * 60)
    logger.info("🤖 BOT INICIADO - Crypto Trading Bot Pro v2.0")
    logger.info("=" * 60)
    logger.info(f"⚙️  Configuração:")
    logger.info(f"   • Pares: {len(PAIRS)} -> {', '.join(PAIRS)}")
    logger.info(f"   • Timeframes: {', '.join(TIMEFRAMES)}")
    logger.info(f"   • Intervalo: {BOT_INTERVAL}s ({BOT_INTERVAL//60}min)")
    logger.info(f"   • Estratégias: {len([s for s in STRATEGIES.values() if s['active']])} ativas")
    logger.info("=" * 60)
    
    # Mensagem inicial no Telegram
    if TELEGRAM_TOKEN and CHAT_ID:
        startup_msg = (
            f"🤖 *Crypto Bot Iniciado*\n"
            f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
            f"📊 Monitorando {len(PAIRS)} pares\n"
            f"⏰ Intervalo: {BOT_INTERVAL//60} minutos\n"
            f"🎯 {len([s for s in STRATEGIES.values() if s['active']])} estratégias ativas\n"
            f"\nBot pronto para operar! ✅"
        )
        send_telegram(startup_msg)
        logger.info("✅ Mensagem inicial enviada para Telegram")
    else:
        logger.warning("⚠️  Telegram não configurado. Sinais não serão enviados.")
    
    # Loop principal
    while True:
        try:
            scan_start = datetime.now()
            logger.info(f"🔍 [{scan_start.strftime('%H:%M:%S')}] Iniciando varredura...")
            
            signals_found = 0
            for symbol in PAIRS:
                signal = analyze_symbol(symbol)
                if signal:
                    logger.info(f"   📢 Sinal encontrado: {signal['direction']} {signal['symbol']}")
                    if send_signal(signal):
                        signals_found += 1
                    time.sleep(2)  # Pausa entre envios
            
            scan_duration = (datetime.now() - scan_start).total_seconds()
            performance_stats["last_scan"] = scan_start.isoformat()
            
            logger.info(f"✅ [{datetime.now().strftime('%H:%M:%S')}] Varredura concluída em {scan_duration:.1f}s")
            logger.info(f"   📊 Sinais encontrados: {signals_found}")
            logger.info(f"   ⏰ Próxima varredura em {BOT_INTERVAL//60} minutos...")
            logger.info("-" * 60)
            
            # Sleep até próxima varredura
            time.sleep(BOT_INTERVAL)
            
        except KeyboardInterrupt:
            logger.info("👋 Bot interrompido pelo usuário")
            break
        except Exception as e:
            logger.error(f"❌ Erro no loop principal: {e}")
            logger.error("⏰ Aguardando 30 segundos antes de retry...")
            time.sleep(30)

# =========================
# MANTER APP ATIVO NO RENDER
# =========================
def keep_alive():
    """Ping automático para manter app ativo no Render free"""
    time.sleep(10)  # Esperar app iniciar
    while True:
        try:
            # Tentar pingar a si mesmo
            requests.get(f"http://localhost:{PORT}/health", timeout=5)
            logger.debug("✅ Ping interno para manter ativo")
        except:
            pass
        time.sleep(180)  # A cada 3 minutos

# =========================
# INICIALIZAÇÃO
# =========================
def main():
    """Função principal"""
    logger.info(f"🚀 Iniciando aplicação na porta {PORT}")
    
    # Iniciar thread para manter ativo (apenas se necessário)
    # alive_thread = threading.Thread(target=keep_alive, daemon=True)
    # alive_thread.start()
    
    # Iniciar bot em thread separada
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    logger.info("🧵 Bot worker iniciado em background")
    
    # Iniciar servidor web
    logger.info(f"🌐 Servidor web iniciando em http://0.0.0.0:{PORT}")
    logger.info(f"📊 Dashboard: http://localhost:{PORT}")
    logger.info(f"🏥 Health: http://localhost:{PORT}/health")
    logger.info(f"📈 Stats: http://localhost:{PORT}/stats")
    
    try:
        app.run(
            host='0.0.0.0',
            port=PORT,
            debug=False,
            use_reloader=False,
            threaded=True
        )
    except Exception as e:
        logger.error(f"❌ Erro no servidor web: {e}")

if __name__ == '__main__':
    main()
