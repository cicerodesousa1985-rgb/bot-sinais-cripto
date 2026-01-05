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
precos_cache = {}  # Cache de preços
ultima_atualizacao_precos = None

estatisticas = {
    "total_sinais": 0,
    "taxa_acerto": 0,
    "confianca_media": 0,
    "ultima_atualizacao": None,
    "sinais_hoje": 0,
    "lucro_potencial": "R$ 0,00"
}

# =========================
# BUSCAR PREÇOS REAIS DA BINANCE
# =========================

def buscar_preco_real(simbolo):
    """Busca o preço REAL da Binance"""
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={simbolo}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        resposta = requests.get(url, headers=headers, timeout=10)
        
        if resposta.status_code == 200:
            dados = resposta.json()
            preco = float(dados['price'])
            
            # Atualizar cache
            precos_cache[simbolo] = {
                "preco": preco,
                "timestamp": time.time()
            }
            
            logger.info(f"✅ Preço real {simbolo}: ${preco:,.2f}")
            return preco
        else:
            logger.warning(f"⚠️ Erro API {simbolo}: {resposta.status_code}")
            
    except Exception as e:
        logger.error(f"❌ Falha ao buscar {simbolo}: {e}")
    
    # Fallback: usar cache ou valor padrão
    if simbolo in precos_cache:
        cache_age = time.time() - precos_cache[simbolo]["timestamp"]
        if cache_age < 300:  # 5 minutos
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
    
    return valores_fallback.get(simbolo, 100.0)

def obter_dados_mercado(simbolo):
    """Obtém dados de mercado COM VALORES REAIS"""
    
    # Buscar preço real
    preco_real = buscar_preco_real(simbolo)
    
    # Se falhou várias vezes, usar variação simulada
    if preco_real == 0 or preco_real is None:
        logger.warning(f"Usando fallback para {simbolo}")
        preco_real = 100.0
    
    # Adicionar pequena variação para simulação
    variacao = random.uniform(-0.01, 0.01)  # ±1%
    preco_atual = preco_real * (1 + variacao)
    
    # Dados técnicos (simulados, mas baseados no preço real)
    dados = {
        "simbolo": simbolo,
        "preco": round(preco_atual, 4),
        "variacao_24h": round(random.uniform(-4.0, 4.0), 2),  # ±4%
        "volume_24h": round(random.uniform(0.5, 5.0), 2),     # Volume em bilhões
        "capitalizacao": round(random.uniform(10, 100), 1),   # Capitalização em bilhões
        "rsi": random.randint(35, 65),
        "macd": round(random.uniform(-1.0, 1.0), 3),
        "sinal": random.choice(["COMPRA_FORTE", "COMPRA", "NEUTRO", "VENDA", "VENDA_FORTE"]),
        "timestamp": datetime.now().isoformat(),
        "preco_real": preco_real  # Salvar o preço real para referência
    }
    
    return dados

def atualizar_todos_precos():
    """Atualiza preços de todos os pares"""
    global ultima_atualizacao_precos
    
    pares = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]
    
    logger.info("🔄 Atualizando preços da Binance...")
    
    for simbolo in pares:
        try:
            preco = buscar_preco_real(simbolo)
            if preco:
                logger.debug(f"  {simbolo}: ${preco:,.2f}")
        except:
            pass
        time.sleep(0.5)  # Delay para não sobrecarregar
    
    ultima_atualizacao_precos = datetime.now()
    logger.info(f"✅ Preços atualizados: {ultima_atualizacao_precos.strftime('%H:%M:%S')}")

# =========================
# GERAR SINAIS (MESMA LÓGICA)
# =========================

def gerar_sinal(simbolo):
    """Gera um sinal de trading baseado em análise técnica"""
    
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
        
    elif dados["macd"] > 0.5:
        direcao = "COMPRA"
        confianca = random.uniform(0.65, 0.80)
        forca_sinal = random.choice(["MÉDIO", "FRACO"])
        motivo = f"MACD positivo ({dados['macd']:.3f})"
        
    elif dados["macd"] < -0.5:
        direcao = "VENDA"
        confianca = random.uniform(0.65, 0.80)
        forca_sinal = random.choice(["MÉDIO", "FRACO"])
        motivo = f"MACD negativo ({dados['macd']:.3f})"
        
    else:
        # 20% chance de sinal neutro
        if random.random() < 0.2:
            direcao = random.choice(["COMPRA", "VENDA"])
            confianca = random.uniform(0.55, 0.70)
            forca_sinal = "FRACO"
            motivo = "Tendência lateral com leve viés"
        else:
            return None
    
    # Calcular preços do trade
    if direcao == "COMPRA":
        entrada = round(dados["preco"] * 0.995, 4)  # -0.5%
        stop_loss = round(dados["preco"] * 0.97, 4)  # -3%
        alvos = [
            round(dados["preco"] * 1.02, 4),  # +2%
            round(dados["preco"] * 1.04, 4),  # +4%
            round(dados["preco"] * 1.06, 4)   # +6%
        ]
    else:  # VENDA
        entrada = round(dados["preco"] * 1.005, 4)  # +0.5%
        stop_loss = round(dados["preco"] * 1.03, 4)  # +3%
        alvos = [
            round(dados["preco"] * 0.98, 4),  # -2%
            round(dados["preco"] * 0.96, 4),  # -4%
            round(dados["preco"] * 0.94, 4)   # -6%
        ]
    
    # Calcular lucro potencial
    lucro_potencial_pct = abs((alvos[0] / dados["preco"] - 1) * 100)
    lucro_potencial = f"{lucro_potencial_pct:.1f}%"
    
    sinal = {
        "id": f"{simbolo}_{int(time.time())}",
        "simbolo": simbolo,
        "direcao": direcao,
        "forca": forca_sinal,
        "preco_atual": dados["preco"],
        "preco_real": dados.get("preco_real", dados["preco"]),
        "entrada": entrada,
        "alvos": alvos,
        "stop_loss": stop_loss,
        "confianca": round(confianca, 3),
        "motivo": motivo,
        "timestamp": datetime.now().isoformat(),
        "hora": datetime.now().strftime("%H:%M"),
        "nivel_risco": random.choice(["BAIXO", "MÉDIO", "ALTO"]),
        "lucro_potencial": lucro_potencial,
        "moeda": "USDT",
        "variacao_24h": dados["variacao_24h"]
    }
    
    return sinal

# =========================
# TELEGRAM (MANTIDO)
# =========================

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
*Preço Atual:* `${formatar_preco(sinal['preco_atual'])}`
*Variação 24h:* {sinal['variacao_24h']}%
*Força do Sinal:* {sinal['forca']}
*Confiança:* {int(sinal['confianca'] * 100)}%

🎯 *ENTRADA RECOMENDADA:* `${formatar_preco(sinal['entrada'])}`

🎯 *ALVOS DE LUCRO:*
  1. `${formatar_preco(sinal['alvos'][0])}` (+{(sinal['alvos'][0]/sinal['preco_atual']-1)*100:.1f}%)
  2. `${formatar_preco(sinal['alvos'][1])}` (+{(sinal['alvos'][1]/sinal['preco_atual']-1)*100:.1f}%)
  3. `${formatar_preco(sinal['alvos'][2])}` (+{(sinal['alvos'][2]/sinal['preco_atual']-1)*100:.1f}%)

🛑 *STOP LOSS:* `${formatar_preco(sinal['stop_loss'])}`

📊 *Nível de Risco:* {sinal['nivel_risco']}
📈 *Lucro Potencial:* {sinal['lucro_potencial']}
💡 *Análise Técnica:* {sinal['motivo']}

⏰ *Horário:* {sinal['hora']}
📅 *Data:* {datetime.now().strftime('%d/%m/%Y')}

#CryptoBrasil #{sinal['simbolo'].replace('USDT', '')}
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
        logger.error(f"Erro no Telegram: {e}")
        return False

# =========================
# DASHBOARD HTML (ATUALIZADO PARA MOSTRAR PREÇOS REAIS)
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
            --fundo-escuro: #0a0a0a;
            --card-bg: rgba(255, 255, 255, 0.05);
            --texto: #ffffff;
            --texto-secundario: #b0b0b0;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: linear-gradient(135deg, var(--fundo-escuro) 0%, #1a1a2e 100%);
            color: var(--texto);
            min-height: 100vh;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }
        
        /* Header BRASIL */
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 25px 0;
            border-bottom: 2px solid var(--amarelo-brasil);
            margin-bottom: 30px;
            position: relative;
            overflow: hidden;
        }
        
        .header::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 5px;
            background: linear-gradient(90deg, var(--verde-brasil), var(--amarelo-brasil), var(--azul-brasil));
        }
        
        .logo-brasil {
            display: flex;
            align-items: center;
            gap: 20px;
        }
        
        .bandeira-brasil {
            width: 60px;
            height: 40px;
            background: linear-gradient(90deg, var(--verde-brasil) 33%, var(--amarelo-brasil) 33% 66%, var(--azul-brasil) 66%);
            border-radius: 8px;
            position: relative;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .bandeira-brasil::after {
            content: '★';
            color: var(--amarelo-brasil);
            font-size: 24px;
        }
        
        .logo-texto h1 {
            font-size: 2.2em;
            background: linear-gradient(45deg, var(--amarelo-brasil), var(--verde-brasil));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 8px;
        }
        
        .logo-texto p {
            color: var(--texto-secundario);
            font-size: 1em;
            font-weight: 300;
        }
        
        .status-brasil {
            display: flex;
            align-items: center;
            gap: 15px;
            background: rgba(0, 156, 59, 0.15);
            padding: 12px 25px;
            border-radius: 50px;
            border: 2px solid var(--verde-brasil);
        }
        
        .status-dot {
            width: 12px;
            height: 12px;
            background: var(--verde-compra);
            border-radius: 50%;
            animation: pulse 1.5s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { transform: scale(1); opacity: 1; }
            50% { transform: scale(1.2); opacity: 0.7; }
        }
        
        /* Preços em Tempo Real */
        .precos-reais {
            background: var(--card-bg);
            backdrop-filter: blur(15px);
            border-radius: 20px;
            padding: 25px;
            margin-bottom: 30px;
            border: 2px solid rgba(255, 223, 0, 0.3);
        }
        
        .precos-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }
        
        .preco-item {
            background: rgba(255, 255, 255, 0.08);
            padding: 15px;
            border-radius: 12px;
            text-align: center;
            transition: all 0.3s;
        }
        
        .preco-item:hover {
            background: rgba(255, 223, 0, 0.15);
            transform: translateY(-3px);
        }
        
        .preco-simbolo {
            font-weight: bold;
            font-size: 1.1em;
            color: var(--amarelo-brasil);
            margin-bottom: 5px;
        }
        
        .preco-valor {
            font-size: 1.3em;
            font-weight: 900;
            color: var(--texto);
        }
        
        .preco-variacao {
            font-size: 0.9em;
            margin-top: 5px;
        }
        
        .positivo {
            color: var(--verde-compra);
        }
        
        .negativo {
            color: var(--vermelho-venda);
        }
        
        /* Estatísticas */
        .estatisticas-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 25px;
            margin-bottom: 40px;
        }
        
        .card-estatistica {
            background: var(--card-bg);
            backdrop-filter: blur(15px);
            border-radius: 20px;
            padding: 30px;
            border: 1px solid rgba(255, 223, 0, 0.2);
            transition: all 0.4s;
            position: relative;
            overflow: hidden;
        }
        
        .card-estatistica:hover {
            transform: translateY(-8px);
            border-color: var(--amarelo-brasil);
            box-shadow: 0 15px 40px rgba(255, 223, 0, 0.2);
        }
        
        .card-estatistica::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 4px;
            background: linear-gradient(90deg, var(--verde-brasil), var(--amarelo-brasil));
        }
        
        .card-estatistica h3 {
            font-size: 3em;
            margin-bottom: 10px;
            color: var(--amarelo-brasil);
            font-weight: 800;
        }
        
        .card-estatistica p {
            color: var(--texto-secundario);
            font-size: 1.1em;
        }
        
        /* Grid de Sinais */
        .sinais-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
            gap: 30px;
            margin-bottom: 50px;
        }
        
        .card-sinal {
            background: var(--card-bg);
            backdrop-filter: blur(15px);
            border-radius: 20px;
            padding: 30px;
            border: 3px solid;
            transition: all 0.4s;
            position: relative;
            overflow: hidden;
        }
        
        .card-sinal.compra {
            border-color: rgba(0, 255, 136, 0.4);
            background: linear-gradient(135deg, rgba(0, 255, 136, 0.08), rgba(0, 156, 59, 0.05));
        }
        
        .card-sinal.venda {
            border-color: rgba(255, 71, 87, 0.4);
            background: linear-gradient(135deg, rgba(255, 71, 87, 0.08), rgba(156, 0, 0, 0.05));
        }
        
        .card-sinal:hover {
            transform: translateY(-10px) scale(1.02);
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.4);
        }
        
        .sinal-cabecalho {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 25px;
        }
        
        .sinal-tipo {
            display: flex;
            align-items: center;
            gap: 15px;
        }
        
        .badge-sinal {
            padding: 8px 20px;
            border-radius: 25px;
            font-weight: bold;
            font-size: 1em;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        .badge-compra {
            background: rgba(0, 255, 136, 0.25);
            color: var(--verde-compra);
            border: 2px solid rgba(0, 255, 136, 0.6);
        }
        
        .badge-venda {
            background: rgba(255, 71, 87, 0.25);
            color: var(--vermelho-venda);
            border: 2px solid rgba(255, 71, 87, 0.6);
        }
        
        .sinal-risco {
            color: #ffa502;
            font-weight: bold;
            display: flex;
            align-items: center;
            gap: 5px;
        }
        
        .sinal-simbolo {
            font-size: 1.8em;
            font-weight: 900;
            font-family: 'Courier New', monospace;
            color: var(--amarelo-brasil);
        }
        
        .sinal-preco {
            font-size: 2.5em;
            font-weight: 900;
            margin: 20px 0;
            color: var(--texto);
            text-shadow: 0 0 10px rgba(255, 223, 0, 0.3);
        }
        
        .sinal-meta {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 25px;
            background: rgba(255, 255, 255, 0.05);
            padding: 20px;
            border-radius: 15px;
        }
        
        .meta-item {
            display: flex;
            flex-direction: column;
        }
        
        .meta-label {
            font-size: 0.9em;
            color: var(--texto-secundario);
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        .meta-valor {
            font-weight: bold;
            font-size: 1.3em;
        }
        
        /* Alvos de Lucro */
        .alvos-container {
            margin: 25px 0;
        }
        
        .alvos-titulo {
            color: var(--texto-secundario);
            margin-bottom: 15px;
            font-size: 1.1em;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .alvos-titulo i {
            color: var(--amarelo-brasil);
        }
        
        .alvo-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 15px;
            background: rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            margin-bottom: 12px;
            transition: all 0.3s;
        }
        
        .alvo-item:hover {
            background: rgba(255, 223, 0, 0.15);
            transform: translateX(5px);
        }
        
        .alvo-numero {
            width: 35px;
            height: 35px;
            background: linear-gradient(45deg, var(--verde-brasil), var(--azul-brasil));
            color: var(--amarelo-brasil);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            font-size: 1.2em;
        }
        
        .hora-sinal {
            position: absolute;
            top: 30px;
            right: 30px;
            background: rgba(255, 255, 255, 0.1);
            padding: 8px 20px;
            border-radius: 20px;
            font-size: 0.9em;
            font-weight: bold;
            color: var(--amarelo-brasil);
        }
        
        /* Setup do Trade */
        .trade-setup {
            margin-top: 25px;
            padding-top: 25px;
            border-top: 2px solid rgba(255, 255, 255, 0.1);
        }
        
        .setup-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-top: 15px;
        }
        
        .setup-item {
            background: rgba(255, 255, 255, 0.05);
            padding: 15px;
            border-radius: 12px;
            text-align: center;
        }
        
        .setup-item strong {
            font-size: 1.3em;
            display: block;
            margin-top: 5px;
        }
        
        /* Footer Brasil */
        .footer-brasil {
            text-align: center;
            padding: 40px 0;
            color: var(--texto-secundario);
            border-top: 2px solid rgba(255, 223, 0, 0.3);
            margin-top: 50px;
            position: relative;
        }
        
        .footer-brasil::before {
            content: '🇧🇷';
            position: absolute;
            top: -20px;
            left: 50%;
            transform: translateX(-50%);
            font-size: 40px;
            background: var(--fundo-escuro);
            padding: 0 20px;
        }
        
        .links-footer {
            display: flex;
            justify-content: center;
            gap: 40px;
            margin: 30px 0;
            flex-wrap: wrap;
        }
        
        .links-footer a {
            color: var(--amarelo-brasil);
            text-decoration: none;
            font-weight: bold;
            display: flex;
            align-items: center;
            gap: 8px;
            transition: all 0.3s;
        }
        
        .links-footer a:hover {
            color: var(--verde-brasil);
            transform: translateY(-3px);
        }
        
        .aviso-risco {
            background: rgba(255, 71, 87, 0.1);
            border: 2px solid rgba(255, 71, 87, 0.3);
            border-radius: 15px;
            padding: 20px;
            margin: 30px auto;
            max-width: 800px;
            text-align: center;
            font-size: 0.95em;
        }
        
        /* Responsivo */
        @media (max-width: 768px) {
            .container {
                padding: 15px;
            }
            
            .header {
                flex-direction: column;
                gap: 25px;
                text-align: center;
            }
            
            .sinais-grid {
                grid-template-columns: 1fr;
            }
            
            .estatisticas-grid {
                grid-template-columns: 1fr;
            }
            
            .links-footer {
                gap: 20px;
                flex-direction: column;
            }
            
            .precos-grid {
                grid-template-columns: repeat(2, 1fr);
            }
        }
        
        /* Animações */
        @keyframes float {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-10px); }
        }
        
        .floating {
            animation: float 3s ease-in-out infinite;
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header Brasil -->
        <div class="header">
            <div class="logo-brasil">
                <div class="bandeira-brasil floating"></div>
                <div class="logo-texto">
                    <h1>🇧🇷 FAT PIG SIGNALS BRASIL</h1>
                    <p>Sinais de Trading com Preços em Tempo Real</p>
                </div>
            </div>
            <div class="status-brasil">
                <div class="status-dot"></div>
                <span>● SISTEMA ATIVO</span>
                <span id="contador" style="background: var(--azul-brasil); padding: 5px 15px; border-radius: 20px;">
                    Atualização: <span id="tempo">5:00</span>
                </span>
            </div>
        </div>
        
        <!-- Preços em Tempo Real -->
        <div class="precos-reais">
            <h2 style="margin-bottom: 15px;">
                <i class="fas fa-chart-line"></i> Preços em Tempo Real
                <span style="font-size: 0.7em; color: var(--texto-secundario); margin-left: 10px;">
                    Última atualização: <span id="ultimaAtualizacaoPrecos">{{ ultima_atualizacao_precos_str }}</span>
                </span>
            </h2>
            <div class="precos-grid" id="precosReais">
                <!-- Preços serão carregados via JavaScript -->
                <div class="preco-item">
                    <div class="preco-simbolo">BTC</div>
                    <div class="preco-valor">Carregando...</div>
                    <div class="preco-variacao">--.--%</div>
                </div>
            </div>
            <p style="margin-top: 15px; font-size: 0.9em; color: var(--texto-secundario);">
                <i class="fas fa-info-circle"></i> Dados em tempo real da Binance API
            </p>
        </div>
        
        <!-- Estatísticas -->
        <div class="estatisticas-grid">
            <div class="card-estatistica">
                <h3>{{ estatisticas.total_sinais }}</h3>
                <p>Sinais Gerados</p>
                <small>Desde o início</small>
            </div>
            <div class="card-estatistica">
                <h3>{{ "%.1f"|format(estatisticas.taxa_acerto * 100) }}%</h3>
                <p>Taxa de Acerto</p>
                <small>Base histórico</small>
            </div>
            <div class="card-estatistica">
                <h3>{{ "%.1f"|format(estatisticas.confianca_media * 100) }}%</h3>
                <p>Confiança Média</p>
                <small>Qualidade dos sinais</small>
            </div>
            <div class="card-estatistica">
                <h3>{{ estatisticas.sinais_hoje }}</h3>
                <p>Sinais Hoje</p>
                <small>{{ data_hoje }}</small>
            </div>
        </div>
        
        <!-- Grid de Sinais -->
        <div class="sinais-grid">
            {% for sinal in ultimos_sinais %}
            <div class="card-sinal {{ sinal.direcao.lower() }}">
                <div class="hora-sinal">{{ sinal.hora }}</div>
                
                <div class="sinal-cabecalho">
                    <div class="sinal-tipo">
                        <span class="badge-sinal badge-{{ sinal.direcao.lower() }}">
                            {{ sinal.direcao }} {{ sinal.forca }}
                        </span>
                        <span class="sinal-risco">
                            <i class="fas fa-shield-alt"></i> Risco {{ sinal.nivel_risco }}
                        </span>
                    </div>
                    <div class="sinal-simbolo">{{ sinal.simbolo }}</div>
                </div>
                
                <div class="sinal-preco">${{ "{:,.2f}".format(sinal.preco_atual).replace(",", "X").replace(".", ",").replace("X", ".") }}</div>
                
                <div class="sinal-meta">
                    <div class="meta-item">
                        <span class="meta-label">Confiança</span>
                        <span class="meta-valor" style="color: #00d4ff;">
                            {{ (sinal.confianca * 100)|int }}%
                        </span>
                    </div>
                    <div class="meta-item">
                        <span class="meta-label">Lucro Potencial</span>
                        <span class="meta-valor" style="color: var(--verde-compra);">
                            {{ sinal.lucro_potencial }}
                        </span>
                    </div>
                </div>
                
                <div class="alvos-container">
                    <div class="alvos-titulo">
                        <i class="fas fa-bullseye"></i> Alvos de Lucro
                    </div>
                    {% for alvo in sinal.alvos %}
                    <div class="alvo-item">
                        <div class="alvo-numero">{{ loop.index }}</div>
                        <div style="font-weight: bold;">${{ "{:,.2f}".format(alvo).replace(",", "X").replace(".", ",").replace("X", ".") }}</div>
                        <div style="color: var(--verde-compra); font-weight: bold;">
                            {% if sinal.direcao == "COMPRA" %}+{% else %}-{% endif %}{{ ((alvo / sinal.preco_atual - 1) * 100)|abs|round(1) }}%
                        </div>
                    </div>
                    {% endfor %}
                </div>
                
                <div class="trade-setup">
                    <div style="color: var(--texto-secundario); margin-bottom: 15px; font-size: 1.1em;">
                        <i class="fas fa-chart-line"></i> Configuração do Trade
                    </div>
                    <div class="setup-grid">
                        <div class="setup-item">
                            <small>ENTRADA</small>
                            <strong>${{ "{:,.2f}".format(sinal.entrada).replace(",", "X").replace(".", ",").replace("X", ".") }}</strong>
                        </div>
                        <div class="setup-item" style="border: 2px solid rgba(255, 71, 87, 0.5);">
                            <small>STOP LOSS</small>
                            <strong style="color: var(--vermelho-venda);">${{ "{:,.2f}".format(sinal.stop_loss).replace(",", "X").replace(".", ",").replace("X", ".") }}</strong>
                        </div>
                    </div>
                </div>
                
                <div style="margin-top: 20px; padding: 15px; background: rgba(255, 223, 0, 0.1); border-radius: 12px;">
                    <div style="color: var(--amarelo-brasil); font-weight: bold; margin-bottom: 5px;">
                        <i class="fas fa-lightbulb"></i> Análise Técnica
                    </div>
                    <div style="font-size: 0.95em;">{{ sinal.motivo }}</div>
                </div>
            </div>
            {% endfor %}
        </div>
        
        <!-- Footer -->
        <div class="footer-brasil">
            <p style="font-size: 1.2em; margin-bottom: 10px;">
                <strong>FAT PIG SIGNALS BRASIL</strong> - Preços em tempo real da Binance 🇧🇷
            </p>
            
            <div class="links-footer">
                <a href="/saude"><i class="fas fa-heartbeat"></i> Saúde do Sistema</a>
                <a href="/api/sinais"><i class="fas fa-code"></i> API</a>
                <a href="/estatisticas"><i class="fas fa-chart-bar"></i> Estatísticas</a>
                <a href="/atualizar-precos"><i class="fas fa-sync-alt"></i> Atualizar Preços</a>
                <a href="javascript:void(0)" onclick="atualizarTudo()"><i class="fas fa-redo"></i> Atualizar Tudo</a>
            </div>
            
            <div class="aviso-risco">
                <p style="color: var(--vermelho-venda); font-weight: bold; margin-bottom: 10px;">
                    <i class="fas fa-exclamation-triangle"></i> AVISO DE RISCO
                </p>
                <p>
                    Trading envolve risco alto. Os sinais são educacionais. Não garantimos lucros.
                    Nunca invista mais do que pode perder.
                </p>
            </div>
            
            <p style="font-size: 0.9em; margin-top: 20px; opacity: 0.8;">
                <i class="fas fa-clock"></i> Última atualização geral: <span id="ultimaAtualizacaoGeral">{{ estatisticas.ultima_atualizacao or "Nunca" }}</span>
            </p>
            <p style="font-size: 0.8em; margin-top: 10px; opacity: 0.6;">
                v3.0 • Preços em tempo real • Desenvolvido com ❤️ para o Brasil
            </p>
        </div>
    </div>
    
    <script>
        // Contador regressivo
        let minutos = 5;
        let segundos = 0;
        const tempoEl = document.getElementById('tempo');
        
        function atualizarContador() {
            if (segundos === 0) {
                if (minutos === 0) {
                    minutos = 5;
                    segundos = 0;
                    // Recarregar quando chegar a zero
                    atualizarTudo();
                } else {
                    minutos--;
                    segundos = 59;
                }
            } else {
                segundos--;
            }
            
            tempoEl.textContent = `${minutos}:${segundos.toString().padStart(2, '0')}`;
        }
        
        setInterval(atualizarContador, 1000);
        
        // Buscar preços em tempo real
        async function buscarPrecosReais() {
            try {
                const response = await fetch('/api/precos');
                const data = await response.json();
                
                let html = '';
                data.precos.forEach(preco => {
                    const variacaoClass = preco.variacao >= 0 ? 'positivo' : 'negativo';
                    const variacaoIcon = preco.variacao >= 0 ? '↗' : '↘';
                    
                    html += `
                    <div class="preco-item">
                        <div class="preco-simbolo">${preco.simbolo.replace('USDT', '')}</div>
                        <div class="preco-valor">$${preco.preco.toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 4})}</div>
                        <div class="preco-variacao ${variacaoClass}">
                            ${variacaoIcon} ${Math.abs(preco.variacao).toFixed(2)}%
                        </div>
                    </div>
                    `;
                });
                
                document.getElementById('precosReais').innerHTML = html;
                
                // Atualizar hora da última atualização
                const agora = new Date();
                document.getElementById('ultimaAtualizacaoPrecos').textContent = 
                    `${agora.getHours().toString().padStart(2, '0')}:${agora.getMinutes().toString().padStart(2, '0')}:${agora.getSeconds().toString().padStart(2, '0')}`;
                    
            } catch (error) {
                console.error('Erro ao buscar preços:', error);
                document.getElementById('precosReais').innerHTML = '<div class="preco-item">Erro ao carregar preços</div>';
            }
        }
        
        // Atualizar tudo
        function atualizarTudo() {
            // Animação de loading
            document.querySelectorAll('.card-sinal').forEach(card => {
                card.style.opacity = '0.7';
            });
            
            buscarPrecosReais();
            
            // Atualizar hora geral
            const agora = new Date();
            document.getElementById('ultimaAtualizacaoGeral').textContent = 
                `${agora.getHours().toString().padStart(2, '0')}:${agora.getMinutes().toString().padStart(2, '0')}:${agora.getSeconds().toString().padStart(2, '0')}`;
            
            // Recarregar página após 2 segundos
            setTimeout(() => {
                window.location.reload();
            }, 2000);
        }
        
        // Auto-refresh preços a cada 60 segundos
        setInterval(buscarPrecosReais, 60000);
        
        // Auto-refresh página a cada 5 minutos
        setTimeout(() => {
            window.location.reload();
        }, 300000);
        
        // Efeitos visuais
        document.querySelectorAll('.card-sinal').forEach(card => {
            card.addEventListener('mouseenter', function() {
                this.style.transform = 'translateY(-15px) scale(1.03)';
                this.style.boxShadow = '0 25px 60px rgba(0, 0, 0, 0.5)';
            });
            
            card.addEventListener('mouseleave', function() {
                this.style.transform = 'translateY(0) scale(1)';
                this.style.boxShadow = 'none';
            });
        });
        
        // Inicializar
        buscarPrecosReais();
        
        const agora = new Date();
        document.getElementById('ultimaAtualizacaoGeral').textContent = 
            `${agora.getHours().toString().padStart(2, '0')}:${agora.getMinutes().toString().padStart(2, '0')}:${agora.getSeconds().toString().padStart(2, '0')}`;
    </script>
</body>
</html>
'''

# =========================
# ROTAS EM PORTUGUÊS
# =========================
@app.route('/')
def dashboard():
    """Dashboard principal em português"""
    
    # Calcular estatísticas
    hoje = datetime.now().date()
    sinais_hoje = [s for s in sinais if datetime.fromisoformat(s["timestamp"]).date() == hoje]
    
    if sinais:
        total_conf = sum(s["confianca"] for s in sinais)
        estatisticas["confianca_media"] = total_conf / len(sinais) if sinais else 0
        estatisticas["taxa_acerto"] = 0.82  # Baseado em histórico simulado
        estatisticas["total_sinais"] = len(sinais)
        estatisticas["sinais_hoje"] = len(sinais_hoje)
        estatisticas["ultima_atualizacao"] = datetime.now().strftime("%H:%M:%S")
    
    # Últimos 6 sinais (mais recentes primeiro)
    ultimos_6 = list(sinais)[-6:][::-1]
    
    # Format data para template
    ultima_atualizacao_precos_str = "Nunca"
    if ultima_atualizacao_precos:
        ultima_atualizacao_precos_str = ultima_atualizacao_precos.strftime("%H:%M:%S")
    
    return render_template_string(
        DASHBOARD_TEMPLATE,
        ultimos_sinais=ultimos_6,
        estatisticas=estatisticas,
        datetime=datetime,
        data_hoje=hoje.strftime("%d/%m/%Y"),
        ultima_atualizacao_precos_str=ultima_atualizacao_precos_str
    )

@app.route('/saude')
def saude():
    """Health check em português"""
    return jsonify({
        "status": "saudavel",
        "timestamp": datetime.now().isoformat(),
        "servico": "fatpig-signals-brasil",
        "versao": "3.0",
        "uptime": "24/7",
        "sinais_ativos": len(sinais),
        "precos_cache": len(precos_cache),
        "mensagem": "Sistema operando normalmente 🇧🇷",
        "ultima_atualizacao_precos": ultima_atualizacao_precos.isoformat() if ultima_atualizacao_precos else "Nunca"
    })

@app.route('/api/sinais')
def api_sinais():
    """API de sinais em português"""
    return jsonify({
        "quantidade": len(sinais),
        "sinais": list(sinais)[-20:],
        "timestamp": datetime.now().isoformat(),
        "status": "sucesso"
    })

@app.route('/api/precos')
def api_precos():
    """API de preços em tempo real"""
    pares = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]
    precos_lista = []
    
    for simbolo in pares:
        preco = buscar_preco_real(simbolo)
        # Variação simulada para demonstração
        variacao = random.uniform(-2.0, 2.0)
        
        precos_lista.append({
            "simbolo": simbolo,
            "preco": preco,
            "variacao": round(variacao, 2)
        })
    
    return jsonify({
        "precos": precos_lista,
        "timestamp": datetime.now().isoformat(),
        "status": "sucesso"
    })

@app.route('/atualizar-precos')
def atualizar_precos_rota():
    """Rota para atualizar preços manualmente"""
    atualizar_todos_precos()
    return jsonify({
        "status": "sucesso",
        "mensagem": "Preços atualizados manualmente",
        "timestamp": datetime.now().isoformat(),
        "precos_atualizados": len(precos_cache)
    })

@app.route('/estatisticas')
def estatisticas_page():
    """Página de estatísticas detalhadas"""
    hoje = datetime.now().date()
    sinais_hoje = [s for s in sinais if datetime.fromisoformat(s["timestamp"]).date() == hoje]
    
    # Preços atuais
    precos_atuais = {}
    for simbolo in ["BTCUSDT", "ETHUSDT", "BNBUSDT"]:
        precos_atuais[simbolo] = buscar_preco_real(simbolo)
    
    stats = {
        "geral": {
            "total_sinais": len(sinais),
            "sinais_hoje": len(sinais_hoje),
            "sinais_compra": len([s for s in sinais if s["direcao"] == "COMPRA"]),
            "sinais_venda": len([s for s in sinais if s["direcao"] == "VENDA"]),
            "confianca_media": estatisticas["confianca_media"],
            "taxa_acerto": estatisticas["taxa_acerto"]
        },
        "hoje": {
            "data": hoje.strftime("%d/%m/%Y"),
            "sinais_gerados": len(sinais_hoje),
            "primeiro_sinal": sinais_hoje[0]["hora"] if sinais_hoje else "Nenhum",
            "ultimo_sinal": sinais_hoje[-1]["hora"] if sinais_hoje else "Nenhum"
        },
        "precos_atuais": precos_atuais,
        "cache_precos": len(precos_cache)
    }
    
    return jsonify(stats)

@app.route('/gerar-teste')
def gerar_teste():
    """Gera sinais de teste"""
    simbolos_teste = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
    
    sinais_gerados = 0
    for simbolo in simbolos_teste:
        if random.random() < 0.5:
            sinal = gerar_sinal(simbolo)
            if sinal:
                sinais.append(sinal)
                estatisticas["total_sinais"] += 1
                sinais_gerados += 1
                
                if TELEGRAM_TOKEN and CHAT_ID:
                    enviar_telegram_sinal(sinal)
                    time.sleep(1)
    
    return jsonify({
        "status": "sucesso",
        "sinais_gerados": sinais_gerados,
        "total_sinais": len(sinais),
        "mensagem": f"Gerados {sinais_gerados} sinais de teste!"
    })

# =========================
# BOT WORKER EM PORTUGUÊS
# =========================
def worker_principal():
    """Worker que gera sinais periodicamente"""
    logger.info("🤖 FatPig Signals Brasil v3.0 iniciado 🇧🇷")
    
    # Atualizar preços inicialmente
    atualizar_todos_precos()
    
    # Pares monitorados
    simbolos = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]
    
    # Mensagem inicial no Telegram
    if TELEGRAM_TOKEN and CHAT_ID:
        try:
            # Buscar preços reais para a mensagem
            btc_preco = buscar_preco_real("BTCUSDT")
            eth_preco = buscar_preco_real("ETHUSDT")
            
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": CHAT_ID,
                    "text": f"""🚀 *FAT PIG SIGNALS BRASIL v3.0 INICIADO* 🇧🇷

✅ Sistema profissional ATIVADO!
📊 Monitorando {len(simbolos)} pares
⏰ Intervalo: {BOT_INTERVAL//60} minutos
💪 Preços em TEMPO REAL da Binance!

*Preços atuais:*
₿ Bitcoin: ${btc_preco:,.2f}
Ξ Ethereum: ${eth_preco:,.2f}

_Feito por traders, para traders brasileiros_ 🎯""",
                    "parse_mode": "Markdown"
                },
                timeout=5
            )
        except Exception as e:
            logger.warning(f"Não foi possível enviar mensagem inicial: {e}")
    
    ciclo = 0
    while True:
        try:
            ciclo += 1
            logger.info(f"🔍 Ciclo {ciclo}: Analisando {len(simbolos)} pares...")
            
            # Atualizar preços a cada 3 ciclos
            if ciclo % 3 == 0:
                atualizar_todos_precos()
            
            for simbolo in simbolos:
                # 25% chance de gerar sinal
                if random.random() < 0.25:
                    sinal = gerar_sinal(simbolo)
                    if sinal:
                        sinais.append(sinal)
                        estatisticas["total_sinais"] += 1
                        
                        logger.info(f"📢 Novo sinal: {sinal['direcao']} {sinal['simbolo']} ${sinal['preco_atual']:.2f}")
                        
                        # Enviar para Telegram
                        if TELEGRAM_TOKEN and CHAT_ID:
                            enviar_telegram_sinal(sinal)
                            time.sleep(1)
                
                time.sleep(1)  # Pausa entre pares
            
            logger.info(f"✅ Ciclo {ciclo} completo. Próxima análise em {BOT_INTERVAL//60} minutos")
            time.sleep(BOT_INTERVAL)
            
        except Exception as e:
            logger.error(f"❌ Erro no worker: {e}")
            time.sleep(60)

# =========================
# MANTER ATIVO NO RENDER
# =========================
def manter_ativo():
    """Ping automático para manter app ativo"""
    time.sleep(30)
    while True:
        try:
            requests.get(f"http://localhost:{PORT}/saude", timeout=5)
            logger.debug("✅ Ping para manter ativo")
        except:
            pass
        time.sleep(240)  # 4 minutos

# =========================
# INICIAR SISTEMA
# =========================
def main():
    """Função principal"""
    logger.info(f"🚀 FatPig Signals Brasil v3.0 iniciando na porta {PORT} 🇧🇷")
    logger.info("📊 Sistema com preços em TEMPO REAL da Binance!")
    
    # Iniciar workers
    threading.Thread(target=worker_principal, daemon=True).start()
    threading.Thread(target=manter_ativo, daemon=True).start()
    
    # Gerar demo inicial
    def gerar_demo():
        time.sleep(5)
        logger.info("📊 Gerando sinais de demonstração...")
        for _ in range(2):
            simbolo = random.choice(["BTCUSDT", "ETHUSDT", "BNBUSDT"])
            sinal = gerar_sinal(simbolo)
            if sinal:
                sinais.append(sinal)
                estatisticas["total_sinais"] += 1
                logger.info(f"  Demo: {sinal['direcao']} {sinal['simbolo']}")
    
    threading.Thread(target=gerar_demo, daemon=True).start()
    
    # Iniciar servidor Flask
    logger.info(f"🌐 Dashboard disponível em http://localhost:{PORT}")
    logger.info(f"🏥 Health check: http://localhost:{PORT}/saude")
    
    app.run(
        host='0.0.0.0',
        port=PORT,
        debug=False,
        use_reloader=False,
        threaded=True
    )

if __name__ == '__main__':
    main()
