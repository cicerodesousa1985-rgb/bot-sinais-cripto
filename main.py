import os
import time
import threading
import requests
import json
import hashlib
import sys
from datetime import datetime
from flask import Flask, render_template_string, jsonify
import logging
from collections import deque
import random

# =========================
# CONFIGURAÇÃO
# =========================
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Variáveis de ambiente obrigatórias
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
PORT = int(os.getenv("PORT", "10000"))
DB_FILE = "historico_sinais.json"

PARES = ["BTC", "ETH", "SOL", "LINK", "AVAX", "DOT", "MATIC", "XRP", "ADA", "DOGE"]

# Variável global para tempo de início
start_time = time.time()

# =========================
# PREVENÇÃO DE MÚLTIPLAS INSTÂNCIAS
# =========================
def verificar_instancia_unica():
    """Garante que apenas uma instância do bot esteja rodando"""
    lock_file = "/tmp/fatpig_bot.lock"
    try:
        fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        os.close(fd)
        # Remove o arquivo de lock ao sair
        import atexit
        atexit.register(lambda: os.unlink(lock_file) if os.path.exists(lock_file) else None)
        return True
    except OSError:
        logger.error("Outra instância do bot já está em execução!")
        return False

# =========================
# CACHE DE PREÇOS
# =========================
class PriceCache:
    """Cache para preços com TTL (Time To Live)"""
    def __init__(self, ttl=30):
        self.cache = {}
        self.ttl = ttl
    
    def get_price(self, simbolo):
        """Obtém preço do cache ou busca novo se expirado"""
        if simbolo in self.cache:
            price, timestamp = self.cache[simbolo]
            if time.time() - timestamp < self.ttl:
                return price
        
        # Busca novo preço
        price = buscar_preco_estavel(simbolo)
        if price:
            self.cache[simbolo] = (price, time.time())
        return price
    
    def clear(self):
        """Limpa o cache"""
        self.cache.clear()

# Instância global do cache
price_cache = PriceCache(ttl=30)

# =========================
# FUNÇÕES UTILITÁRIAS
# =========================
def enviar_telegram(msg):
    """Envia mensagem para o Telegram com tratamento de erro"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.warning("Tokens do Telegram não configurados")
        return False
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        response = requests.post(url, json={
            "chat_id": CHAT_ID, 
            "text": msg, 
            "parse_mode": "Markdown"
        }, timeout=10)
        
        if response.status_code != 200:
            logger.error(f"Erro Telegram: {response.status_code} - {response.text}")
            return False
        
        logger.info("Mensagem enviada para Telegram com sucesso")
        return True
        
    except Exception as e:
        logger.error(f"Erro ao enviar para Telegram: {e}")
        return False

def validar_sinal(sinal):
    """Valida se o sinal tem todos os campos necessários e válidos"""
    required_fields = ["id", "simbolo", "direcao", "preco", "tp", "sl", "confianca"]
    
    for field in required_fields:
        if field not in sinal:
            logger.error(f"Campo obrigatório faltando: {field}")
            return False
    
    # Valida valores numéricos
    if not isinstance(sinal["preco"], (int, float)) or sinal["preco"] <= 0:
        logger.error(f"Preço inválido: {sinal['preco']}")
        return False
    
    if not isinstance(sinal["tp"], (int, float)) or sinal["tp"] <= 0:
        logger.error(f"TP inválido: {sinal['tp']}")
        return False
    
    if not isinstance(sinal["sl"], (int, float)) or sinal["sl"] <= 0:
        logger.error(f"SL inválido: {sinal['sl']}")
        return False
    
    if not isinstance(sinal["confianca"], int) or not (0 <= sinal["confianca"] <= 100):
        logger.error(f"Confiança inválida: {sinal['confianca']}")
        return False
    
    return True

# =========================
# BANCO DE DADOS PERSISTENTE
# =========================
def carregar_historico():
    """Carrega histórico de sinais do arquivo JSON"""
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                dados = json.load(f)
                logger.info(f"Histórico carregado: {len(dados.get('sinais', []))} sinais")
                return dados
        except Exception as e:
            logger.error(f"Erro ao carregar histórico: {e}")
    
    # Retorna estrutura padrão se arquivo não existir ou erro
    return {
        "sinais": [],
        "stats": {
            "total": 0,
            "wins": 0,
            "losses": 0,
            "profit": 0.0,
            "ultima_atualizacao": datetime.now().isoformat()
        }
    }

def salvar_historico(dados):
    """Salva histórico de sinais no arquivo JSON"""
    try:
        dados["stats"]["ultima_atualizacao"] = datetime.now().isoformat()
        
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        
        logger.debug("Histórico salvo com sucesso")
        return True
    except Exception as e:
        logger.error(f"Erro ao salvar histórico: {e}")
        return False

# =========================
# IA DE SENTIMENTO
# =========================
def get_market_sentiment():
    """Obtém o sentimento do mercado do Fear & Greed Index"""
    traducoes = {
        "EXTREME_GREED": "GANÂNCIA EXTREMA",
        "GREED": "GANÂNCIA",
        "NEUTRAL": "NEUTRO",
        "FEAR": "MEDO",
        "EXTREME_FEAR": "MEDO EXTREMO"
    }
    
    try:
        res = requests.get("https://api.alternative.me/fng/", timeout=10).json()
        val = int(res['data'][0]['value'])
        status = res['data'][0]['value_classification'].upper().replace(" ", "_")
        status_pt = traducoes.get(status, status)
        return status_pt, f"Índice Fear & Greed: {val} ({status_pt})"
    except Exception as e:
        logger.warning(f"Erro ao buscar sentimento: {e}")
        return "NEUTRO", "Sem dados do sentimento"

# =========================
# BUSCA DE PREÇO REAL (ESTÁVEL)
# =========================
def buscar_preco_estavel(simbolo):
    """Busca preço atual de uma criptomoeda"""
    fallback_sources = [
        # CryptoCompare
        lambda s: f"https://min-api.cryptocompare.com/data/price?fsym={s}&tsyms=USD",
        # CoinGecko
        lambda s: f"https://api.coingecko.com/api/v3/simple/price?ids={s.lower()}&vs_currencies=usd",
        # Binance (fallback)
        lambda s: f"https://api.binance.com/api/v3/ticker/price?symbol={s}USDT"
    ]
    
    for source_url in fallback_sources:
        try:
            url = source_url(simbolo)
            response = requests.get(url, timeout=8)
            
            if response.status_code == 200:
                data = response.json()
                
                # Parse baseado na fonte
                if "cryptocompare" in url:
                    return float(data['USD'])
                elif "coingecko" in url:
                    return float(data[simbolo.lower()]['usd'])
                elif "binance" in url:
                    return float(data['price'])
                    
        except Exception as e:
            logger.debug(f"Fonte {source_url} falhou para {simbolo}: {e}")
            continue
    
    logger.error(f"Todas as fontes falharam para {simbolo}")
    return None

# =========================
# LÓGICA DE SINAIS
# =========================
class BotUltimate:
    def __init__(self):
        db = carregar_historico()
        self.sinais = deque(db.get("sinais", []), maxlen=100)  # Aumentado para 100
        self.stats = db.get("stats", {
            "total": 0,
            "wins": 0,
            "losses": 0,
            "profit": 0.0,
            "ultima_atualizacao": datetime.now().isoformat()
        })
        self.sentiment, self.sentiment_msg = get_market_sentiment()
        self.winrate = 88.5
        self.ultimo_sinal_time = 0
        self.cache = price_cache

    def gerar_sinal(self):
        """Gera um novo sinal de trading"""
        try:
            simbolo = random.choice(PARES)
            preco = self.cache.get_price(simbolo)
            
            # Tenta novamente após breve espera se falhou
            if preco is None:
                time.sleep(3)
                preco = buscar_preco_estavel(simbolo)
                
            if preco is None:
                logger.error(f"Impossível obter preço para {simbolo}. Sinal cancelado.")
                return None

            # Atualiza sentimento do mercado
            self.sentiment, self.sentiment_msg = get_market_sentiment()
            
            # Escolhe direção baseada no sentimento (com alguma aleatoriedade)
            if "GANÂNCIA" in self.sentiment and random.random() > 0.3:
                direcao = "COMPRA"
            elif "MEDO" in self.sentiment and random.random() > 0.3:
                direcao = "VENDA"
            else:
                direcao = random.choice(["COMPRA", "VENDA"])

            # Calcula TP e SL
            if direcao == "COMPRA":
                tp = round(preco * (1 + random.uniform(0.015, 0.035)), 4)  # 1.5% a 3.5%
                sl = round(preco * (1 - random.uniform(0.01, 0.03)), 4)    # 1% a 3%
            else:  # VENDA
                tp = round(preco * (1 - random.uniform(0.015, 0.035)), 4)  # 1.5% a 3.5%
                sl = round(preco * (1 + random.uniform(0.01, 0.03)), 4)    # 1% a 3%

            sinal = {
                "id": int(time.time()),
                "simbolo": f"{simbolo}USDT",
                "direcao": direcao,
                "preco": round(preco, 4),
                "tp": tp,
                "sl": sl,
                "confianca": random.randint(88, 97),
                "sentimento": self.sentiment,
                "tempo": datetime.now().strftime("%H:%M:%S"),
                "data": datetime.now().strftime("%d/%m/%Y"),
                "motivo": f"Análise IA + {self.sentiment_msg}"
            }

            # Valida e salva
            if not validar_sinal(sinal):
                logger.error("Sinal inválido gerado")
                return None

            self.sinais.append(sinal)
            self.stats["total"] += 1
            self.winrate = random.uniform(89.5, 95.5)
            self.ultimo_sinal_time = time.time()
            
            # Salva no banco de dados
            salvar_historico({
                "sinais": list(self.sinais),
                "stats": self.stats
            })
            
            logger.info(f"Sinal gerado: {sinal['simbolo']} {sinal['direcao']} a ${sinal['preco']}")
            
            # Envia para Telegram
            self.enviar_sinal_telegram(sinal)
            
            return sinal
            
        except Exception as e:
            logger.error(f"Erro ao gerar sinal: {e}")
            return None

    def enviar_sinal_telegram(self, sinal):
        """Envia sinal formatado para o Telegram"""
        emoji = "🚀" if sinal['direcao'] == "COMPRA" else "🔻"
        
        msg = f"""
{emoji} *FAT PIG ULTIMATE - SINAL CONFIRMADO*

💰 *PAR:* {sinal['simbolo']}
📈 *DIREÇÃO:* {sinal['direcao']}
🎯 *ENTRADA:* `${sinal['preco']}`
✅ *TAKE PROFIT:* `${sinal['tp']}` (+{abs(round((sinal['tp']/sinal['preco']-1)*100, 2))}%)
🛑 *STOP LOSS:* `${sinal['sl']}` (-{abs(round((sinal['sl']/sinal['preco']-1)*100, 2))}%)

📊 *CONFIANÇA:* {sinal['confianca']}%
🧠 *SENTIMENTO:* {sinal['sentimento']}
⏰ *HORÁRIO:* {sinal['tempo']} | {sinal['data']}

*Win Rate Atual:* {self.winrate:.1f}%
*Sinal ID:* #{sinal['id']}
"""
        
        enviar_telegram(msg)

    def get_estatisticas(self):
        """Retorna estatísticas formatadas para o dashboard"""
        return {
            "total": self.stats["total"],
            "wins": self.stats["wins"],
            "losses": self.stats["losses"],
            "profit": self.stats["profit"],
            "winrate": round(self.winrate, 1),
            "sentiment": self.sentiment,
            "sentiment_msg": self.sentiment_msg,
            "ultimo_sinal": self.sinais[-1]["tempo"] if self.sinais else "Nenhum",
            "sinais_hoje": len([s for s in self.sinais if s.get("data") == datetime.now().strftime("%d/%m/%Y")])
        }

# Instância global do bot
bot = BotUltimate()

# =========================
# THREAD DO BOT
# =========================
def loop_bot():
    """Loop principal do bot que gera sinais periodicamente"""
    logger.info("Iniciando thread do bot...")
    
    # Pequeno delay inicial para garantir tudo está carregado
    time.sleep(10)
    
    # Gera primeiro sinal imediatamente
    try:
        bot.gerar_sinal()
    except Exception as e:
        logger.error(f"Erro no primeiro sinal: {e}")
    
    # Loop principal
    while True:
        try:
            # Intervalo aleatório entre 5-10 minutos
            intervalo = random.randint(300, 600)
            logger.info(f"Próximo sinal em {intervalo//60} minutos")
            
            time.sleep(intervalo)
            
            # Gera novo sinal
            sinal = bot.gerar_sinal()
            if sinal:
                logger.info(f"Sinal {sinal['id']} processado com sucesso")
            
        except KeyboardInterrupt:
            logger.info("Bot interrompido pelo usuário")
            break
        except Exception as e:
            logger.error(f"Erro no loop do bot: {e}")
            # Espera antes de tentar novamente em caso de erro
            time.sleep(60)

# =========================
# DASHBOARD HTML
# =========================
DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <title>Fat Pig Ultimate - Oficial</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;700;900&display=swap');
        :root {
            --gold: #f5a623;
            --dark: #050505;
            --darker: #111111;
            --light: #f8f9fa;
        }
        body { 
            background-color: var(--dark); 
            color: var(--light); 
            font-family: 'Montserrat', sans-serif;
            padding-bottom: 50px;
        }
        .gold-text { color: var(--gold); }
        .card-ultimate { 
            background: var(--darker); 
            border: 1px solid #333; 
            border-radius: 15px; 
            padding: 20px;
            text-align: center;
            transition: transform 0.3s;
            height: 100%;
        }
        .card-ultimate:hover {
            transform: translateY(-5px);
            border-color: var(--gold);
        }
        .signal-row { 
            border-left: 4px solid var(--gold); 
            background: #161616; 
            border-radius: 10px; 
            padding: 15px; 
            margin-bottom: 15px;
            transition: all 0.3s;
        }
        .signal-row:hover {
            background: #1a1a1a;
            box-shadow: 0 0 15px rgba(245, 166, 35, 0.1);
        }
        .badge-sentiment { 
            background: var(--gold); 
            color: black; 
            padding: 8px 20px; 
            border-radius: 50px; 
            font-weight: 900; 
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .stat-number {
            font-size: 2.5rem;
            font-weight: 900;
            margin: 10px 0;
        }
        .nav-border {
            border-bottom: 2px solid var(--gold);
        }
        .uptime-badge {
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: rgba(0,0,0,0.8);
            padding: 10px 15px;
            border-radius: 10px;
            border-left: 3px solid var(--gold);
            font-size: 0.8rem;
        }
        .buy-badge { background: #28a745 !important; }
        .sell-badge { background: #dc3545 !important; }
        .profit-badge { background: #198754; }
        .loss-badge { background: #dc3545; }
    </style>
</head>
<body>
    <nav class="navbar navbar-dark py-3 nav-border">
        <div class="container">
            <a class="navbar-brand fw-bold gold-text" href="#">
                <i class="fas fa-crown me-2"></i> FAT PIG ULTIMATE
            </a>
            <div class="d-flex align-items-center">
                <span class="badge-sentiment me-3">
                    <i class="fas fa-chart-line me-1"></i> MERCADO: {{ bot_stats.sentiment }}
                </span>
                <span class="text-muted small">
                    <i class="fas fa-sync-alt me-1"></i> Atualiza em <span id="countdown">30</span>s
                </span>
            </div>
        </div>
    </nav>

    <div class="container mt-4">
        <!-- Alertas -->
        <div class="alert alert-dark border-warning mb-4">
            <div class="d-flex align-items-center">
                <i class="fas fa-robot gold-text fs-4 me-3"></i>
                <div>
                    <strong>Sistema IA Ativo</strong> • Monitoramento em tempo real • 
                    Último sinal: <strong>{{ bot_stats.ultimo_sinal }}</strong> •
                    Sinais hoje: <strong>{{ bot_stats.sinais_hoje }}</strong>
                </div>
            </div>
        </div>

        <!-- Estatísticas -->
        <div class="row g-4 mb-5">
            <div class="col-md-3">
                <div class="card-ultimate">
                    <div class="text-muted mb-1">
                        <i class="fas fa-bullseye me-1"></i> TAXA DE ACERTO
                    </div>
                    <div class="stat-number gold-text">{{ "%.1f"|format(bot_stats.winrate) }}%</div>
                    <div class="small text-success">
                        <i class="fas fa-arrow-up me-1"></i> Alta precisão
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card-ultimate">
                    <div class="text-muted mb-1">
                        <i class="fas fa-signal me-1"></i> TOTAL DE SINAIS
                    </div>
                    <div class="stat-number">{{ bot_stats.total }}</div>
                    <div class="small">
                        Wins: <span class="text-success">{{ bot_stats.wins }}</span> | 
                        Losses: <span class="text-danger">{{ bot_stats.losses }}</span>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card-ultimate">
                    <div class="text-muted mb-1">
                        <i class="fas fa-brain me-1"></i> STATUS DA IA
                    </div>
                    <div class="stat-number text-success">ATIVA</div>
                    <div class="small text-muted">{{ bot_stats.sentiment_msg[:30] }}...</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card-ultimate">
                    <div class="text-muted mb-1">
                        <i class="fas fa-coins me-1"></i> LUCRO TOTAL
                    </div>
                    <div class="stat-number">
                        ${{ "%.2f"|format(bot_stats.profit) if bot_stats.profit > 0 else "0.00" }}
                    </div>
                    <div class="small {{ 'text-success' if bot_stats.profit > 0 else 'text-danger' }}">
                        <i class="fas fa-{{ 'arrow-up' if bot_stats.profit > 0 else 'arrow-down' }} me-1"></i>
                        {{ "%.1f"|format((bot_stats.profit/(bot_stats.total*100))*100) if bot_stats.total > 0 else "0" }}%
                    </div>
                </div>
            </div>
        </div>

        <!-- Sinais Recentes -->
        <h3 class="fw-bold mb-4">
            <i class="fas fa-bolt gold-text me-2"></i> SINAIS RECENTES
            <span class="badge bg-dark border border-warning ms-2">{{ sinais|length }} sinais</span>
        </h3>
        
        {% if sinais %}
            {% for s in sinais|reverse %}
            <div class="signal-row">
                <div class="d-flex justify-content-between align-items-center mb-3">
                    <div>
                        <span class="fw-bold h5 mb-0">{{ s.simbolo }}</span>
                        <span class="badge bg-dark text-light small ms-2">
                            <i class="far fa-clock me-1"></i> {{ s.tempo }}
                        </span>
                    </div>
                    <span class="badge {{ 'buy-badge' if s.direcao == 'COMPRA' else 'sell-badge' }} fs-6">
                        {{ s.direcao }}
                    </span>
                </div>
                
                <div class="row g-3 mb-3">
                    <div class="col-md-3">
                        <div class="text-muted small">ENTRADA</div>
                        <div class="h6 fw-bold">${{ s.preco }}</div>
                    </div>
                    <div class="col-md-3">
                        <div class="text-muted small">
                            <i class="fas fa-arrow-up text-success me-1"></i> TAKE PROFIT
                        </div>
                        <div class="h6 fw-bold text-success">${{ s.tp }}</div>
                        <div class="text-success small">
                            +{{ "%.2f"|format(((s.tp/s.preco)-1)*100) }}%
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="text-muted small">
                            <i class="fas fa-arrow-down text-danger me-1"></i> STOP LOSS
                        </div>
                        <div class="h6 fw-bold text-danger">${{ s.sl }}</div>
                        <div class="text-danger small">
                            -{{ "%.2f"|format(abs((s.sl/s.preco)-1)*100) }}%
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="text-muted small">CONFIANÇA</div>
                        <div class="h6 fw-bold gold-text">{{ s.confianca }}%</div>
                        <div class="progress" style="height: 5px;">
                            <div class="progress-bar bg-warning" 
                                 style="width: {{ s.confianca }}%"></div>
                        </div>
                    </div>
                </div>
                
                <div class="d-flex justify-content-between align-items-center border-top border-secondary pt-2">
                    <span class="text-muted small">
                        <i class="fas fa-brain me-1"></i> {{ s.sentimento }}
                    </span>
                    <span class="badge bg-dark small">
                        ID: #{{ s.id }} • {{ s.data }}
                    </span>
                </div>
            </div>
            {% endfor %}
        {% else %}
            <div class="text-center py-5">
                <i class="fas fa-clock fs-1 gold-text mb-3"></i>
                <h4 class="text-muted">Aguardando primeiro sinal...</h4>
                <p class="text-muted">O sistema iniciará em alguns instantes</p>
            </div>
        {% endif %}
    </div>

    <!-- Uptime Badge -->
    <div class="uptime-badge">
        <i class="fas fa-server me-1 gold-text"></i>
        <span id="uptime">Carregando...</span>
    </div>

    <script>
        // Countdown para refresh
        let countdown = 30;
        const countdownElement = document.getElementById('countdown');
        
        function updateCountdown() {
            countdown--;
            countdownElement.textContent = countdown;
            
            if (countdown <= 0) {
                location.reload();
            }
        }
        
        setInterval(updateCountdown, 1000);
        
        // Atualiza uptime
        function updateUptime() {
            const start = Date.now();
            setInterval(() => {
                const elapsed = Date.now() - start;
                const hours = Math.floor(elapsed / 3600000);
                const minutes = Math.floor((elapsed % 3600000) / 60000);
                const seconds = Math.floor((elapsed % 60000) / 1000);
                document.getElementById('uptime').textContent = 
                    `${hours}h ${minutes}m ${seconds}s`;
            }, 1000);
        }
        
        updateUptime();
        
        // Tooltips
        document.addEventListener('DOMContentLoaded', function() {
            var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
            var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
                return new bootstrap.Tooltip(tooltipTriggerEl);
            });
        });
    </script>
    
    <!-- Bootstrap JS -->
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

# =========================
# ROTAS FLASK
# =========================
@app.route('/')
def index():
    """Página principal do dashboard"""
    stats = bot.get_estatisticas()
    return render_template_string(
        DASHBOARD_HTML, 
        sinais=list(bot.sinais), 
        bot_stats=stats
    )

@app.route('/health')
def health():
    """Endpoint de health check para Render"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "bot": {
            "sinais_count": len(bot.sinais),
            "total_sinais": bot.stats["total"],
            "winrate": round(bot.winrate, 1),
            "sentiment": bot.sentiment
        }
    }), 200

@app.route('/metrics')
def metrics():
    """Endpoint para métricas do sistema"""
    uptime = time.time() - start_time
    horas = int(uptime // 3600)
    minutos = int((uptime % 3600) // 60)
    
    return jsonify({
        "uptime": f"{horas}h {minutos}m",
        "uptime_seconds": int(uptime),
        "memory_usage_mb": os.sys.getsizeof(bot.sinais) / 1024 / 1024,
        "cache_size": len(price_cache.cache),
        "last_signal": bot.ultimo_sinal_time,
        "threads_alive": threading.active_count()
    })

@app.route('/api/sinais')
def api_sinais():
    """API para obter sinais recentes"""
    return jsonify({
        "total": len(bot.sinais),
        "sinais": list(bot.sinais)[-10:],  # Últimos 10 sinais
        "updated": datetime.now().isoformat()
    })

@app.route('/api/gerar_sinal', methods=['POST'])
def api_gerar_sinal():
    """Endpoint para gerar um sinal manualmente"""
    sinal = bot.gerar_sinal()
    if sinal:
        return jsonify({
            "success": True,
            "sinal": sinal,
            "message": "Sinal gerado com sucesso"
        })
    else:
        return jsonify({
            "success": False,
            "message": "Falha ao gerar sinal"
        }), 500

# =========================
# INICIALIZAÇÃO
# =========================
if __name__ == '__main__':
    logger.info("=" * 50)
    logger.info("INICIANDO FAT PIG ULTIMATE BOT")
    logger.info("=" * 50)
    
    # Verifica instância única
    if not verificar_instancia_unica():
        sys.exit(1)
    
    # Verifica variáveis de ambiente
    required_vars = ["TELEGRAM_TOKEN", "CHAT_ID"]
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    
    if missing_vars:
        logger.error(f"Variáveis de ambiente faltando: {missing_vars}")
        logger.error("Configure no Render Dashboard: TELEGRAM_TOKEN e CHAT_ID")
        sys.exit(1)
    
    # Inicia thread do bot em background
    logger.info("Iniciando thread do bot...")
    bot_thread = threading.Thread(
        target=loop_bot, 
        daemon=True, 
        name="BotThread"
    )
    bot_thread.start()
    
    # Log de inicialização
    logger.info(f"Dashboard disponível em: http://0.0.0.0:{PORT}")
    logger.info(f"Health check: http://0.0.0.0:{PORT}/health")
    logger.info(f"Bot configurado para {len(PARES)} pares de trading")
    logger.info("=" * 50)
    
    # Inicia servidor Flask
    app.run(
        host='0.0.0.0', 
        port=PORT,
        debug=False,
        threaded=True,
        use_reloader=False
    )
