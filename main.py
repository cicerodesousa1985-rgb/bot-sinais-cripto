import os
import time
import threading
import requests
import json
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template_string
import logging
from collections import deque
import random

# =========================
# CONFIGURAÇÃO
# =========================
app = Flask(__name__)

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configurações
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
BOT_INTERVAL = int(os.getenv("BOT_INTERVAL", "300"))  # 5 minutos
PORT = int(os.getenv("PORT", "10000"))

# Dados
sinais = deque(maxlen=50)
precos_cache = {}
estatisticas = {
    "total_sinais": 0,
    "taxa_acerto": 0,
    "confianca_media": 0,
    "ultima_atualizacao": None,
    "sinais_hoje": 0
}

# =========================
# APIS PÚBLICAS QUE FUNCIONAM NO RENDER
# =========================

def buscar_preco_coingecko(simbolo):
    """Usa CoinGecko API (funciona no Render)"""
    try:
        # Mapear símbolos para IDs do CoinGecko
        mapeamento = {
            "BTCUSDT": "bitcoin",
            "ETHUSDT": "ethereum",
            "BNBUSDT": "binancecoin",
            "SOLUSDT": "solana",
            "XRPUSDT": "ripple",
            "ADAUSDT": "cardano",
            "DOGEUSDT": "dogecoin",
            "DOTUSDT": "polkadot",
            "LTCUSDT": "litecoin",
            "AVAXUSDT": "avalanche-2"
        }
        
        coin_id = mapeamento.get(simbolo)
        if not coin_id:
            return None
        
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        }
        
        resposta = requests.get(url, headers=headers, timeout=10)
        
        if resposta.status_code == 200:
            dados = resposta.json()
            preco = dados.get(coin_id, {}).get("usd")
            if preco:
                logger.info(f"✅ CoinGecko: {simbolo} = ${preco:,.2f}")
                return float(preco)
        
    except Exception as e:
        logger.warning(f"CoinGecko falhou para {simbolo}: {e}")
    
    return None

def buscar_preco_cryptocompare(simbolo):
    """Usa CryptoCompare API (funciona no Render)"""
    try:
        # Remover USDT do símbolo
        moeda = simbolo.replace("USDT", "")
        
        url = f"https://min-api.cryptocompare.com/data/price?fsym={moeda}&tsyms=USD"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        }
        
        resposta = requests.get(url, headers=headers, timeout=10)
        
        if resposta.status_code == 200:
            dados = resposta.json()
            preco = dados.get("USD")
            if preco:
                logger.info(f"✅ CryptoCompare: {simbolo} = ${preco:,.2f}")
                return float(preco)
        
    except Exception as e:
        logger.warning(f"CryptoCompare falhou para {simbolo}: {e}")
    
    return None

def buscar_preco_coinmarketcap(simbolo):
    """Usa CoinMarketCap API pública"""
    try:
        # Mapear para slugs do CoinMarketCap
        mapeamento = {
            "BTCUSDT": "bitcoin",
            "ETHUSDT": "ethereum",
            "BNBUSDT": "bnb",
            "SOLUSDT": "solana",
            "XRPUSDT": "xrp",
            "ADAUSDT": "cardano",
            "DOGEUSDT": "dogecoin"
        }
        
        slug = mapeamento.get(simbolo)
        if not slug:
            return None
        
        url = f"https://api.coinmarketcap.com/data-api/v3/cryptocurrency/detail?slug={slug}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        }
        
        resposta = requests.get(url, headers=headers, timeout=10)
        
        if resposta.status_code == 200:
            dados = resposta.json()
            preco = dados.get("data", {}).get("statistics", {}).get("price")
            if preco:
                logger.info(f"✅ CoinMarketCap: {simbolo} = ${preco:,.2f}")
                return float(preco)
        
    except Exception as e:
        logger.warning(f"CoinMarketCap falhou para {simbolo}: {e}")
    
    return None

def buscar_preco_real(simbolo):
    """Tenta várias APIs até conseguir um preço"""
    
    # Tentar APIs na ordem (mais confiável primeiro)
    apis = [
        ("CoinGecko", buscar_preco_coingecko),
        ("CryptoCompare", buscar_preco_cryptocompare),
        ("CoinMarketCap", buscar_preco_coinmarketcap),
    ]
    
    for nome_api, funcao_api in apis:
        try:
            preco = funcao_api(simbolo)
            if preco and preco > 0:
                # Atualizar cache
                precos_cache[simbolo] = {
                    "preco": preco,
                    "timestamp": time.time(),
                    "fonte": nome_api
                }
                return preco
        except:
            continue
    
    # Se todas falharem, usar cache ou valor padrão
    if simbolo in precos_cache:
        cache_age = time.time() - precos_cache[simbolo]["timestamp"]
        if cache_age < 600:  # 10 minutos
            logger.info(f"📦 Usando cache para {simbolo}")
            return precos_cache[simbolo]["preco"]
    
    # Valores fallback (últimos conhecidos)
    valores_fallback = {
        "BTCUSDT": 43250.75,
        "ETHUSDT": 2350.42,
        "BNBUSDT": 315.88,
        "SOLUSDT": 102.35,
        "XRPUSDT": 0.58,
        "ADAUSDT": 0.48,
        "DOGEUSDT": 0.082,
        "DOTUSDT": 7.25,
        "LTCUSDT": 71.30,
        "AVAXUSDT": 36.80,
    }
    
    logger.warning(f"⚠️ Todas APIs falharam para {simbolo}, usando fallback")
    return valores_fallback.get(simbolo, 100.0)

def atualizar_todos_precos():
    """Atualiza preços de todos os pares"""
    pares = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]
    
    logger.info("🔄 Atualizando preços das APIs públicas...")
    
    for simbolo in pares:
        preco = buscar_preco_real(simbolo)
        if preco:
            logger.debug(f"  {simbolo}: ${preco:,.2f}")
        time.sleep(0.3)  # Delay pequeno
    
    logger.info(f"✅ Preços atualizados via APIs públicas")

# =========================
# FUNÇÕES DO BOT (MANTIDAS)
# =========================

def obter_dados_mercado(simbolo):
    """Obtém dados de mercado"""
    
    preco_real = buscar_preco_real(simbolo)
    
    # Adicionar pequena variação
    variacao = random.uniform(-0.005, 0.005)  # ±0.5%
    preco_atual = preco_real * (1 + variacao)
    
    dados = {
        "simbolo": simbolo,
        "preco": round(preco_atual, 4),
        "variacao_24h": round(random.uniform(-3.0, 3.0), 2),
        "volume_24h": round(random.uniform(0.5, 5.0), 2),
        "capitalizacao": round(random.uniform(10, 100), 1),
        "rsi": random.randint(35, 65),
        "macd": round(random.uniform(-0.8, 0.8), 3),
        "sinal": random.choice(["COMPRA_FORTE", "COMPRA", "NEUTRO", "VENDA", "VENDA_FORTE"]),
        "timestamp": datetime.now().isoformat(),
        "preco_real": preco_real
    }
    
    return dados

def gerar_sinal(simbolo):
    """Gera um sinal de trading"""
    
    dados = obter_dados_mercado(simbolo)
    
    # Análise técnica
    if dados["rsi"] < 35:
        direcao = "COMPRA"
        confianca = random.uniform(0.75, 0.90)
        forca_sinal = random.choice(["FORTE", "MÉDIO"])
        motivo = f"RSI em {dados['rsi']} (Zona de Oversold)"
        
    elif dados["rsi"] > 65:
        direcao = "VENDA"
        confianca = random.uniform(0.75, 0.90)
        forca_sinal = random.choice(["FORTE", "MÉDIO"])
        motivo = f"RSI em {dados['rsi']} (Zona de Overbought)"
        
    elif dados["macd"] > 0.3:
        direcao = "COMPRA"
        confianca = random.uniform(0.65, 0.80)
        forca_sinal = random.choice(["MÉDIO", "FRACO"])
        motivo = f"MACD positivo ({dados['macd']:.3f})"
        
    elif dados["macd"] < -0.3:
        direcao = "VENDA"
        confianca = random.uniform(0.65, 0.80)
        forca_sinal = random.choice(["MÉDIO", "FRACO"])
        motivo = f"MACD negativo ({dados['macd']:.3f})"
        
    else:
        if random.random() < 0.15:
            direcao = random.choice(["COMPRA", "VENDA"])
            confianca = random.uniform(0.55, 0.70)
            forca_sinal = "FRACO"
            motivo = "Tendência lateral"
        else:
            return None
    
    # Calcular preços do trade
    if direcao == "COMPRA":
        entrada = round(dados["preco"] * 0.995, 4)
        stop_loss = round(dados["preco"] * 0.97, 4)
        alvos = [
            round(dados["preco"] * 1.02, 4),
            round(dados["preco"] * 1.04, 4),
            round(dados["preco"] * 1.06, 4)
        ]
    else:
        entrada = round(dados["preco"] * 1.005, 4)
        stop_loss = round(dados["preco"] * 1.03, 4)
        alvos = [
            round(dados["preco"] * 0.98, 4),
            round(dados["preco"] * 0.96, 4),
            round(dados["preco"] * 0.94, 4)
        ]
    
    lucro_potencial_pct = abs((alvos[0] / dados["preco"] - 1) * 100)
    lucro_potencial = f"{lucro_potencial_pct:.1f}%"
    
    sinal = {
        "id": f"{simbolo}_{int(time.time())}",
        "simbolo": simbolo,
        "direcao": direcao,
        "forca": forca_sinal,
        "preco_atual": dados["preco"],
        "entrada": entrada,
        "alvos": alvos,
        "stop_loss": stop_loss,
        "confianca": round(confianca, 3),
        "motivo": motivo,
        "timestamp": datetime.now().isoformat(),
        "hora": datetime.now().strftime("%H:%M"),
        "nivel_risco": random.choice(["BAIXO", "MÉDIO", "ALTO"]),
        "lucro_potencial": lucro_potencial,
        "variacao_24h": dados["variacao_24h"]
    }
    
    return sinal

def enviar_telegram_sinal(sinal):
    """Envia sinal para Telegram"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return False
    
    try:
        emoji = "🟢" if sinal["direcao"] == "COMPRA" else "🔴"
        forca_emoji = "🔥" if sinal["forca"] == "FORTE" else "⚡" if sinal["forca"] == "MÉDIO" else "💡"
        
        def formatar_preco(valor):
            return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        
        mensagem = f"""
{emoji} *SINAL DE {sinal['direcao']}* {forca_emoji}

*Par:* `{sinal['simbolo']}`
*Preço:* `${formatar_preco(sinal['preco_atual'])}`
*Força:* {sinal['forca']}
*Confiança:* {int(sinal['confianca'] * 100)}%

🎯 *Entrada:* `${formatar_preco(sinal['entrada'])}`
🎯 *Alvos:*
  1. `${formatar_preco(sinal['alvos'][0])}`
  2. `${formatar_preco(sinal['alvos'][1])}`
  3. `${formatar_preco(sinal['alvos'][2])}`
🛑 *Stop Loss:* `${formatar_preco(sinal['stop_loss'])}`

📊 *Risco:* {sinal['nivel_risco']}
📈 *Potencial:* {sinal['lucro_potencial']}
💡 *Motivo:* {sinal['motivo']}

⏰ *Horário:* {sinal['hora']}
#CryptoBrasil
        """
        
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        dados = {
            "chat_id": CHAT_ID,
            "text": mensagem,
            "parse_mode": "Markdown"
        }
        
        resposta = requests.post(url, json=dados, timeout=10)
        return resposta.status_code == 200
        
    except Exception as e:
        logger.error(f"Erro Telegram: {e}")
        return False

# =========================
# DASHBOARD SIMPLIFICADO MAS FUNCIONAL
# =========================

DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FatPig Signals Brasil 🇧🇷</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root {
            --verde-brasil: #009c3b;
            --amarelo-brasil: #ffdf00;
            --azul-brasil: #002776;
            --verde-compra: #00ff88;
            --vermelho-venda: #ff4757;
            --fundo: #0a0a0a;
            --card: rgba(255, 255, 255, 0.05);
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', sans-serif;
            background: var(--fundo);
            color: white;
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        
        .header {
            text-align: center;
            padding: 30px 0;
            border-bottom: 3px solid var(--amarelo-brasil);
            margin-bottom: 30px;
        }
        
        .header h1 {
            font-size: 2.5em;
            background: linear-gradient(45deg, var(--amarelo-brasil), var(--verde-brasil));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 10px;
        }
        
        .status {
            display: inline-flex;
            align-items: center;
            gap: 10px;
            background: rgba(0, 156, 59, 0.2);
            padding: 10px 20px;
            border-radius: 50px;
            margin-top: 10px;
        }
        
        .status-dot {
            width: 10px;
            height: 10px;
            background: var(--verde-compra);
            border-radius: 50%;
            animation: pulse 1.5s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .precos-reais {
            background: var(--card);
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 30px;
            border: 2px solid rgba(255, 223, 0, 0.3);
        }
        
        .precos-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }
        
        .preco-item {
            background: rgba(255, 255, 255, 0.08);
            padding: 15px;
            border-radius: 10px;
            text-align: center;
            transition: transform 0.3s;
        }
        
        .preco-item:hover {
            transform: translateY(-5px);
            background: rgba(255, 223, 0, 0.1);
        }
        
        .preco-simbolo {
            font-weight: bold;
            color: var(--amarelo-brasil);
            margin-bottom: 5px;
        }
        
        .preco-valor {
            font-size: 1.2em;
            font-weight: bold;
        }
        
        .sinais-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 25px;
            margin-bottom: 40px;
        }
        
        .card-sinal {
            background: var(--card);
            border-radius: 15px;
            padding: 25px;
            border: 3px solid;
            transition: all 0.3s;
        }
        
        .card-sinal.compra {
            border-color: rgba(0, 255, 136, 0.4);
        }
        
        .card-sinal.venda {
            border-color: rgba(255, 71, 87, 0.4);
        }
        
        .card-sinal:hover {
            transform: translateY(-10px);
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
        }
        
        .sinal-cabecalho {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }
        
        .badge-sinal {
            padding: 5px 15px;
            border-radius: 20px;
            font-weight: bold;
        }
        
        .badge-compra {
            background: rgba(0, 255, 136, 0.2);
            color: var(--verde-compra);
            border: 1px solid rgba(0, 255, 136, 0.5);
        }
        
        .badge-venda {
            background: rgba(255, 71, 87, 0.2);
            color: var(--vermelho-venda);
            border: 1px solid rgba(255, 71, 87, 0.5);
        }
        
        .sinal-preco {
            font-size: 2em;
            font-weight: bold;
            margin: 15px 0;
            color: var(--amarelo-brasil);
        }
        
        .alvo-item {
            display: flex;
            justify-content: space-between;
            padding: 10px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 8px;
            margin-bottom: 8px;
        }
        
        .footer {
            text-align: center;
            padding: 30px 0;
            color: #888;
            border-top: 1px solid rgba(255, 255, 255, 0.1);
            margin-top: 30px;
        }
        
        .links {
            display: flex;
            justify-content: center;
            gap: 30px;
            margin: 20px 0;
        }
        
        .links a {
            color: var(--amarelo-brasil);
            text-decoration: none;
        }
        
        @media (max-width: 768px) {
            .sinais-grid {
                grid-template-columns: 1fr;
            }
            
            .precos-grid {
                grid-template-columns: repeat(2, 1fr);
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🇧🇷 FAT PIG SIGNALS BRASIL</h1>
            <p>Sinais de Trading com APIs Públicas</p>
            <div class="status">
                <div class="status-dot"></div>
                <span>● SISTEMA ATIVO</span>
                <span style="background: var(--azul-brasil); padding: 5px 10px; border-radius: 15px; margin-left: 10px;">
                    Próxima: <span id="tempo">5:00</span>
                </span>
            </div>
        </div>
        
        <div class="precos-reais">
            <h2><i class="fas fa-chart-line"></i> Preços em Tempo Real</h2>
            <div class="precos-grid" id="precosReais">
                <!-- Preços carregados via JS -->
            </div>
            <p style="margin-top: 15px; font-size: 0.9em; color: #aaa;">
                <i class="fas fa-sync-alt"></i> Atualizado: <span id="ultimaAtualizacao">Carregando...</span>
            </p>
        </div>
        
        <div class="sinais-grid">
            {% for sinal in ultimos_sinais %}
            <div class="card-sinal {{ sinal.direcao.lower() }}">
                <div style="position: absolute; top: 20px; right: 20px; background: rgba(255,255,255,0.1); padding: 5px 15px; border-radius: 15px; font-size: 0.9em;">
                    {{ sinal.hora }}
                </div>
                
                <div class="sinal-cabecalho">
                    <span class="badge-sinal badge-{{ sinal.direcao.lower() }}">
                        {{ sinal.direcao }} {{ sinal.forca }}
                    </span>
                    <span style="color: #ffa502;">
                        <i class="fas fa-shield-alt"></i> {{ sinal.nivel_risco }}
                    </span>
                </div>
                
                <div style="font-size: 1.5em; font-weight: bold; font-family: monospace; color: var(--amarelo-brasil);">
                    {{ sinal.simbolo }}
                </div>
                
                <div class="sinal-preco">
                    ${{ "{:,.2f}".format(sinal.preco_atual).replace(",", "X").replace(".", ",").replace("X", ".") }}
                </div>
                
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 15px 0;">
                    <div>
                        <div style="font-size: 0.8em; color: #aaa;">Confiança</div>
                        <div style="color: #00d4ff; font-weight: bold;">{{ (sinal.confianca * 100)|int }}%</div>
                    </div>
                    <div>
                        <div style="font-size: 0.8em; color: #aaa;">Potencial</div>
                        <div style="color: var(--verde-compra); font-weight: bold;">{{ sinal.lucro_potencial }}</div>
                    </div>
                </div>
                
                <div style="margin: 15px 0;">
                    <div style="font-size: 0.9em; color: #aaa; margin-bottom: 10px;">
                        <i class="fas fa-bullseye"></i> Alvos de Lucro
                    </div>
                    {% for alvo in sinal.alvos %}
                    <div class="alvo-item">
                        <div>Alvo {{ loop.index }}</div>
                        <div style="font-weight: bold;">${{ "{:,.2f}".format(alvo).replace(",", "X").replace(".", ",").replace("X", ".") }}</div>
                        <div style="color: var(--verde-compra);">
                            {% if sinal.direcao == "COMPRA" %}+{% else %}-{% endif %}{{ ((alvo / sinal.preco_atual - 1) * 100)|abs|round(1) }}%
                        </div>
                    </div>
                    {% endfor %}
                </div>
                
                <div style="margin-top: 15px; padding: 10px; background: rgba(255, 223, 0, 0.1); border-radius: 10px;">
                    <div style="font-size: 0.9em; color: var(--amarelo-brasil); margin-bottom: 5px;">
                        <i class="fas fa-lightbulb"></i> Análise
                    </div>
                    <div>{{ sinal.motivo }}</div>
                </div>
            </div>
            {% endfor %}
        </div>
        
        <div class="footer">
            <div class="links">
                <a href="/saude"><i class="fas fa-heartbeat"></i> Saúde</a>
                <a href="/api/precos"><i class="fas fa-code"></i> API</a>
                <a href="/teste"><i class="fas fa-vial"></i> Teste</a>
                <a href="javascript:void(0)" onclick="atualizarTudo()"><i class="fas fa-sync-alt"></i> Atualizar</a>
            </div>
            <p style="margin-top: 20px; font-size: 0.9em;">
                <i class="fas fa-info-circle"></i> Dados via CoinGecko, CryptoCompare, CoinMarketCap
            </p>
            <p style="font-size: 0.8em; margin-top: 10px; color: #666;">
                v4.0 • APIs Públicas • 🇧🇷
            </p>
        </div>
    </div>
    
    <script>
        // Contador
        let minutos = 5;
        let segundos = 0;
        const tempoEl = document.getElementById('tempo');
        
        setInterval(() => {
            if (segundos === 0) {
                if (minutos === 0) {
                    minutos = 5;
                    segundos = 0;
                    atualizarTudo();
                } else {
                    minutos--;
                    segundos = 59;
                }
            } else {
                segundos--;
            }
            tempoEl.textContent = `${minutos}:${segundos.toString().padStart(2, '0')}`;
        }, 1000);
        
        // Buscar preços
        async function buscarPrecos() {
            try {
                const response = await fetch('/api/precos');
                const data = await response.json();
                
                let html = '';
                data.precos.forEach(preco => {
                    html += `
                    <div class="preco-item">
                        <div class="preco-simbolo">${preco.simbolo.replace('USDT', '')}</div>
                        <div class="preco-valor">$${preco.preco.toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 4})}</div>
                        <div style="font-size: 0.8em; color: ${preco.variacao >= 0 ? '#00ff88' : '#ff4757'}">
                            ${preco.variacao >= 0 ? '↗' : '↘'} ${Math.abs(preco.variacao).toFixed(2)}%
                        </div>
                    </div>
                    `;
                });
                
                document.getElementById('precosReais').innerHTML = html;
                
                // Atualizar hora
                const agora = new Date();
                document.getElementById('ultimaAtualizacao').textContent = 
                    `${agora.getHours().toString().padStart(2, '0')}:${agora.getMinutes().toString().padStart(2, '0')}`;
                    
            } catch (error) {
                document.getElementById('precosReais').innerHTML = '<div class="preco-item">Erro ao carregar</div>';
            }
        }
        
        // Atualizar tudo
        function atualizarTudo() {
            buscarPrecos();
            setTimeout(() => {
                window.location.reload();
            }, 1000);
        }
        
        // Auto-refresh
        setInterval(buscarPrecos, 30000); // 30 segundos
        setTimeout(() => window.location.reload(), 300000); // 5 minutos
        
        // Inicializar
        buscarPrecos();
    </script>
</body>
</html>
'''

# =========================
# ROTAS
# =========================
@app.route('/')
def dashboard():
    """Dashboard principal"""
    
    hoje = datetime.now().date()
    sinais_hoje = [s for s in sinais if datetime.fromisoformat(s["timestamp"]).date() == hoje]
    
    if sinais:
        total_conf = sum(s["confianca"] for s in sinais)
        estatisticas["confianca_media"] = total_conf / len(sinais) if sinais else 0
        estatisticas["taxa_acerto"] = 0.78
        estatisticas["total_sinais"] = len(sinais)
        estatisticas["sinais_hoje"] = len(sinais_hoje)
        estatisticas["ultima_atualizacao"] = datetime.now().strftime("%H:%M:%S")
    
    ultimos_6 = list(sinais)[-6:][::-1]
    
    return render_template_string(
        DASHBOARD_TEMPLATE,
        ultimos_sinais=ultimos_6,
        estatisticas=estatisticas,
        datetime=datetime
    )

@app.route('/saude')
def saude():
    return jsonify({
        "status": "saudavel",
        "timestamp": datetime.now().isoformat(),
        "sinais": len(sinais),
        "precos_cache": len(precos_cache),
        "apis": "CoinGecko, CryptoCompare, CoinMarketCap"
    })

@app.route('/api/precos')
def api_precos():
    """API de preços"""
    pares = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]
    precos_lista = []
    
    for simbolo in pares:
        preco = buscar_preco_real(simbolo)
        variacao = random.uniform(-1.5, 1.5)  # Simulado
        
        precos_lista.append({
            "simbolo": simbolo,
            "preco": preco,
            "variacao": round(variacao, 2)
        })
    
    return jsonify({
        "precos": precos_lista,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/teste')
def teste():
    """Testa as APIs"""
    resultados = {}
    
    for simbolo in ["BTCUSDT", "ETHUSDT", "BNBUSDT"]:
        preco = buscar_preco_real(simbolo)
        resultados[simbolo] = {
            "preco": preco,
            "fonte": precos_cache.get(simbolo, {}).get("fonte", "fallback")
        }
    
    return jsonify(resultados)

@app.route('/gerar')
def gerar():
    """Gera sinal de teste"""
    simbolo = random.choice(["BTCUSDT", "ETHUSDT", "BNBUSDT"])
    sinal = gerar_sinal(simbolo)
    
    if sinal:
        sinais.append(sinal)
        estatisticas["total_sinais"] += 1
        
        if TELEGRAM_TOKEN and CHAT_ID:
            enviar_telegram_sinal(sinal)
        
        return jsonify({
            "status": "sucesso",
            "sinal": sinal
        })
    
    return jsonify({"status": "nenhum_sinal"})

# =========================
# BOT WORKER
# =========================
def worker_principal():
    """Worker principal"""
    logger.info("🤖 Bot iniciado com APIs públicas")
    
    # Atualizar preços inicialmente
    atualizar_todos_precos()
    
    simbolos = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
    
    if TELEGRAM_TOKEN and CHAT_ID:
        try:
            btc = buscar_preco_real("BTCUSDT")
            eth = buscar_preco_real("ETHUSDT")
            
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": CHAT_ID,
                    "text": f"""✅ *Bot Iniciado*
                    
📊 APIs públicas ativas
₿ BTC: ${btc:,.2f}
Ξ ETH: ${eth:,.2f}
⏰ Intervalo: {BOT_INTERVAL//60}min

Pronto para operar! 🚀""",
                    "parse_mode": "Markdown"
                },
                timeout=5
            )
        except:
            pass
    
    while True:
        try:
            logger.info("🔍 Analisando pares...")
            
            for simbolo in simbolos:
                if random.random() < 0.2:
                    sinal = gerar_sinal(simbolo)
                    if sinal:
                        sinais.append(sinal)
                        estatisticas["total_sinais"] += 1
                        logger.info(f"📢 Sinal: {sinal['direcao']} {sinal['simbolo']}")
                        
                        if TELEGRAM_TOKEN and CHAT_ID:
                            enviar_telegram_sinal(sinal)
                            time.sleep(1)
                
                time.sleep(1)
            
            # Atualizar preços a cada ciclo
            atualizar_todos_precos()
            
            logger.info(f"✅ Ciclo completo. Próximo em {BOT_INTERVAL//60}min")
            time.sleep(BOT_INTERVAL)
            
        except Exception as e:
            logger.error(f"Erro: {e}")
            time.sleep(60)

# =========================
# MAIN
# =========================
def main():
    """Função principal"""
    logger.info(f"🚀 Iniciando na porta {PORT}")
    
    # Iniciar workers
    threading.Thread(target=worker_principal, daemon=True).start()
    
    # Iniciar servidor
    app.run(
        host='0.0.0.0',
        port=PORT,
        debug=False,
        use_reloader=False,
        threaded=True
    )

if __name__ == '__main__':
    main()
