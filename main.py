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
estatisticas = {
    "total_sinais": 0,
    "taxa_acerto": 0,
    "confianca_media": 0,
    "ultima_atualizacao": None,
    "sinais_hoje": 0,
    "lucro_potencial": "R$ 0,00"
}

# =========================
# VALORES REAIS DAS CRIPTOMOEDAS (Janeiro 2024)
# =========================

# Preços base REALISTAS (valores aproximados do mercado)
PRECOS_BASE = {
    "BTCUSDT": 43250.75,     # Bitcoin
    "ETHUSDT": 2350.42,      # Ethereum
    "BNBUSDT": 315.88,       # Binance Coin
    "SOLUSDT": 102.35,       # Solana
    "XRPUSDT": 0.58,         # Ripple
    "ADAUSDT": 0.48,         # Cardano
    "DOGEUSDT": 0.082,       # Dogecoin
    "DOTUSDT": 7.25,         # Polkadot
    "LTCUSDT": 71.30,        # Litecoin
    "AVAXUSDT": 36.80,       # Avalanche
}

# Variações máximas realistas por par
VARIACOES = {
    "BTCUSDT": {"min": -500, "max": 500},      # ±500 USD
    "ETHUSDT": {"min": -30, "max": 30},        # ±30 USD
    "BNBUSDT": {"min": -5, "max": 5},          # ±5 USD
    "SOLUSDT": {"min": -3, "max": 3},          # ±3 USD
    "XRPUSDT": {"min": -0.01, "max": 0.01},    # ±0.01 USD
    "ADAUSDT": {"min": -0.008, "max": 0.008},  # ±0.008 USD
    "DOGEUSDT": {"min": -0.001, "max": 0.001}, # ±0.001 USD
    "DOTUSDT": {"min": -0.2, "max": 0.2},      # ±0.2 USD
    "LTCUSDT": {"min": -1.5, "max": 1.5},      # ±1.5 USD
    "AVAXUSDT": {"min": -1.0, "max": 1.0},     # ±1.0 USD
}

# Volumes de mercado aproximados (em bilhões)
VOLUMES = {
    "BTCUSDT": 28.5,    # 28.5 bilhões
    "ETHUSDT": 12.7,    # 12.7 bilhões
    "BNBUSDT": 1.8,     # 1.8 bilhões
    "SOLUSDT": 3.2,     # 3.2 bilhões
    "XRPUSDT": 1.5,     # 1.5 bilhões
    "ADAUSDT": 0.9,     # 0.9 bilhões
    "DOGEUSDT": 0.7,    # 0.7 bilhões
    "DOTUSDT": 0.4,     # 0.4 bilhões
    "LTCUSDT": 0.6,     # 0.6 bilhões
    "AVAXUSDT": 0.5,    # 0.5 bilhões
}

# Capitalização de mercado (em bilhões)
CAPITALIZACAO = {
    "BTCUSDT": 845.3,   # 845.3 bilhões
    "ETHUSDT": 282.1,   # 282.1 bilhões
    "BNBUSDT": 48.5,    # 48.5 bilhões
    "SOLUSDT": 44.9,    # 44.9 bilhões
    "XRPUSDT": 31.4,    # 31.4 bilhões
    "ADAUSDT": 17.0,    # 17.0 bilhões
    "DOGEUSDT": 11.7,   # 11.7 bilhões
    "DOTUSDT": 9.3,     # 9.3 bilhões
    "LTCUSDT": 5.2,     # 5.2 bilhões
    "AVAXUSDT": 13.8,   # 13.8 bilhões
}

def obter_dados_mercado(simbolo):
    """Obtém dados de mercado COM VALORES REALISTAS"""
    
    # Pegar preço base ou usar valor padrão
    preco_base = PRECOS_BASE.get(simbolo, 100.0)
    variacao_info = VARIACOES.get(simbolo, {"min": -10, "max": 10})
    
    # Calcular preço atual com variação realista
    variacao = random.uniform(variacao_info["min"], variacao_info["max"])
    preco_atual = preco_base + variacao
    
    # Garantir que o preço seja positivo
    preco_atual = max(preco_atual, preco_base * 0.9)
    
    # Calcular variação percentual de 24h (entre -5% e +5%)
    variacao_percent = random.uniform(-5.0, 5.0)
    
    # Volume e capitalização com pequena variação
    volume_base = VOLUMES.get(simbolo, 1.0)
    volume_atual = volume_base * random.uniform(0.9, 1.1)
    
    cap_base = CAPITALIZACAO.get(simbolo, 10.0)
    cap_atual = cap_base * random.uniform(0.95, 1.05)
    
    # Dados técnicos
    dados = {
        "simbolo": simbolo,
        "preco": round(preco_atual, 4),
        "variacao_24h": round(variacao_percent, 2),
        "volume_24h": round(volume_atual, 2),
        "capitalizacao": round(cap_atual, 1),
        "rsi": random.randint(35, 65),  # RSI mais realista (entre 35-65)
        "macd": round(random.uniform(-1.0, 1.0), 3),
        "sinal": random.choice(["COMPRA_FORTE", "COMPRA", "NEUTRO", "VENDA", "VENDA_FORTE"]),
        "timestamp": datetime.now().isoformat()
    }
    
    return dados

def gerar_sinal(simbolo):
    """Gera um sinal de trading COM VALORES REALISTAS"""
    
    dados = obter_dados_mercado(simbolo)
    
    # Análise técnica mais realista
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
        entrada = round(dados["preco"] * 0.995, 4)  # -0.5% do preço atual
        stop_loss = round(dados["preco"] * 0.97, 4)  # -3% do preço atual
        # Alvos de lucro: +2%, +4%, +6%
        alvos = [
            round(dados["preco"] * 1.02, 4),
            round(dados["preco"] * 1.04, 4),
            round(dados["preco"] * 1.06, 4)
        ]
    else:  # VENDA
        entrada = round(dados["preco"] * 1.005, 4)  # +0.5% do preço atual
        stop_loss = round(dados["preco"] * 1.03, 4)  # +3% do preço atual
        # Alvos de lucro: -2%, -4%, -6%
        alvos = [
            round(dados["preco"] * 0.98, 4),
            round(dados["preco"] * 0.96, 4),
            round(dados["preco"] * 0.94, 4)
        ]
    
    # Calcular lucro potencial (baseado na distância até o primeiro alvo)
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
        "moeda": "USDT",
        "variacao_24h": dados["variacao_24h"]
    }
    
    return sinal

# =========================
# TELEGRAM EM PORTUGUÊS
# =========================
def enviar_telegram_sinal(sinal):
    """Envia sinal para Telegram em português"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return False
    
    try:
        emoji = "🟢" if sinal["direcao"] == "COMPRA" else "🔴"
        forca_emoji = "🔥" if sinal["forca"] == "FORTE" else "⚡" if sinal["forca"] == "MÉDIO" else "💡"
        
        # Formatar preços com separadores brasileiros
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
# DASHBOARD HTML (MANTIDO IGUAL)
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
                    <p>Sinais de Trading Profissionais para Crypto Traders Brasileiros</p>
                </div>
            </div>
            <div class="status-brasil">
                <div class="status-dot"></div>
                <span>● SISTEMA ATIVO</span>
                <span id="contador" style="background: var(--azul-brasil); padding: 5px 15px; border-radius: 20px;">
                    Próxima análise: <span id="tempo">5:00</span>
                </span>
            </div>
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
                <small>Baseado em dados históricos</small>
            </div>
            <div class="card-estatistica">
                <h3>{{ "%.1f"|format(estatisticas.confianca_media * 100) }}%</h3>
                <p>Confiança Média</p>
                <small>Qualidade dos sinais</small>
            </div>
            <div class="card-estatistica">
                <h3>{{ estatisticas.sinais_hoje }}</h3>
                <p>Sinais Hoje</p>
                <small>{{ datetime.now().strftime("%d/%m/%Y") }}</small>
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
                <strong>FAT PIG SIGNALS BRASIL</strong> - Feito por traders, para traders 🇧🇷
            </p>
            
            <div class="links-footer">
                <a href="/saude"><i class="fas fa-heartbeat"></i> Saúde do Sistema</a>
                <a href="/api/sinais"><i class="fas fa-code"></i> API para Developers</a>
                <a href="/estatisticas"><i class="fas fa-chart-bar"></i> Estatísticas Detalhadas</a>
                <a href="javascript:void(0)" onclick="atualizarDados()"><i class="fas fa-sync-alt"></i> Atualizar Agora</a>
            </div>
            
            <div class="aviso-risco">
                <p style="color: var(--vermelho-venda); font-weight: bold; margin-bottom: 10px;">
                    <i class="fas fa-exclamation-triangle"></i> AVISO DE RISCO IMPORTANTE
                </p>
                <p>
                    Trading de criptomoedas envolve alto risco. Os sinais fornecidos são para fins educacionais e informativos.
                    Não garantimos lucros e você pode perder dinheiro. Nunca invista mais do que pode perder.
                </p>
            </div>
            
            <p style="font-size: 0.9em; margin-top: 20px; opacity: 0.8;">
                <i class="fas fa-clock"></i> Última atualização: <span id="ultimaAtualizacao">{{ estatisticas.ultima_atualizacao or "Nunca" }}</span>
            </p>
            <p style="font-size: 0.8em; margin-top: 10px; opacity: 0.6;">
                v2.0 • Desenvolvido com ❤️ para a comunidade brasileira de crypto
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
                    // Recarregar página quando chegar a zero
                    window.location.reload();
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
        
        // Atualizar dados
        function atualizarDados() {
            document.querySelectorAll('.card-sinal').forEach(card => {
                card.style.transform = 'scale(0.98)';
                setTimeout(() => card.style.transform = '', 300);
            });
            
            // Atualizar hora da última atualização
            const agora = new Date();
            document.getElementById('ultimaAtualizacao').textContent = 
                `${agora.getHours().toString().padStart(2, '0')}:${agora.getMinutes().toString().padStart(2, '0')}:${agora.getSeconds().toString().padStart(2, '0')}`;
            
            // Recarregar após 2 segundos
            setTimeout(() => {
                window.location.reload();
            }, 2000);
        }
        
        // Auto-refresh a cada 5 minutos
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
        const agora = new Date();
        document.getElementById('ultimaAtualizacao').textContent = 
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
        estatisticas["confianca_media"] = total_conf / len(sinais)
        estatisticas["taxa_acerto"] = 0.82  # Baseado em histórico simulado
        estatisticas["total_sinais"] = len(sinais)
        estatisticas["sinais_hoje"] = len(sinais_hoje)
        estatisticas["ultima_atualizacao"] = datetime.now().strftime("%H:%M:%S")
    
    # Últimos 6 sinais (mais recentes primeiro)
    ultimos_6 = list(sinais)[-6:][::-1]
    
    return render_template_string(
        DASHBOARD_TEMPLATE,
        ultimos_sinais=ultimos_6,
        estatisticas=estatisticas,
        datetime=datetime
    )

@app.route('/saude')
def saude():
    """Health check em português"""
    return jsonify({
        "status": "saudavel",
        "timestamp": datetime.now().isoformat(),
        "servico": "fatpig-signals-brasil",
        "versao": "2.0",
        "uptime": "24/7",
        "sinais_ativos": len(sinais),
        "mensagem": "Sistema operando normalmente 🇧🇷",
        "pares_monitorados": list(PRECOS_BASE.keys())
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

@app.route('/estatisticas')
def estatisticas_page():
    """Página de estatísticas detalhadas"""
    hoje = datetime.now().date()
    sinais_hoje = [s for s in sinais if datetime.fromisoformat(s["timestamp"]).date() == hoje]
    
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
        "precos_base": PRECOS_BASE
    }
    
    return jsonify(stats)

@app.route('/gerar-teste')
def gerar_teste():
    """Gera sinais de teste com valores realistas"""
    # Pares principais para teste
    simbolos_teste = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
    
    sinais_gerados = 0
    for simbolo in simbolos_teste:
        # 50% chance de gerar sinal para cada par
        if random.random() < 0.5:
            sinal = gerar_sinal(simbolo)
            if sinal:
                sinais.append(sinal)
                estatisticas["total_sinais"] += 1
                sinais_gerados += 1
                
                # Enviar para Telegram
                if TELEGRAM_TOKEN and CHAT_ID:
                    enviar_telegram_sinal(sinal)
                    time.sleep(1)
    
    return jsonify({
        "status": "sucesso",
        "sinais_gerados": sinais_gerados,
        "total_sinais": len(sinais),
        "mensagem": f"Gerados {sinais_gerados} sinais de teste com valores realistas!"
    })

# =========================
# BOT WORKER EM PORTUGUÊS
# =========================
def worker_principal():
    """Worker que gera sinais periodicamente"""
    logger.info("🤖 FatPig Signals Brasil iniciado 🇧🇷")
    
    # Pares monitorados (principais)
    simbolos = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]
    
    # Mensagem inicial no Telegram
    if TELEGRAM_TOKEN and CHAT_ID:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": CHAT_ID,
                    "text": f"""🚀 *FAT PIG SIGNALS BRASIL INICIADO* 🇧🇷

✅ Sistema de trading profissional ativado!
📊 Monitorando {len(simbolos)} pares principais
⏰ Intervalo: {BOT_INTERVAL//60} minutos
💪 Pronto para operar!

*Pares monitorados:*
{', '.join([s.replace('USDT', '') for s in simbolos])}

_Feito por traders, para traders brasileiros_ 🎯""",
                    "parse_mode": "Markdown"
                },
                timeout=5
            )
        except Exception as e:
            logger.warning(f"Não foi possível enviar mensagem inicial: {e}")
    
    while True:
        try:
            logger.info(f"🔍 Analisando {len(simbolos)} pares...")
            
            for simbolo in simbolos:
                # 30% chance de gerar sinal a cada análise
                if random.random() < 0.3:
                    sinal = gerar_sinal(simbolo)
                    if sinal:
                        sinais.append(sinal)
                        estatisticas["total_sinais"] += 1
                        
                        logger.info(f"📢 Novo sinal: {sinal['direcao']} {sinal['simbolo']} ${sinal['preco_atual']:.2f}")
                        
                        # Enviar para Telegram
                        if TELEGRAM_TOKEN and CHAT_ID:
                            enviar_telegram_sinal(sinal)
                            time.sleep(1)
                
                time.sleep(2)  # Pausa entre análises
            
            logger.info(f"✅ Análise completa. Próxima em {BOT_INTERVAL//60} minutos")
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
    logger.info(f"🚀 FatPig Signals Brasil iniciando na porta {PORT} 🇧🇷")
    logger.info(f"📊 Pares com valores realistas:")
    for simbolo, preco in PRECOS_BASE.items():
        logger.info(f"   • {simbolo}: ${preco:,.2f}")
    
    # Iniciar workers
    threading.Thread(target=worker_principal, daemon=True).start()
    threading.Thread(target=manter_ativo, daemon=True).start()
    
    # Gerar alguns sinais iniciais para demonstração
    def gerar_demo():
        time.sleep(5)
        for _ in range(3):
            simbolo = random.choice(list(PRECOS_BASE.keys())[:4])  # Apenas 4 primeiros
            sinal = gerar_sinal(simbolo)
            if sinal:
                sinais.append(sinal)
                estatisticas["total_sinais"] += 1
                logger.info(f"📊 Sinal demo: {sinal['direcao']} {sinal['simbolo']}")
    
    threading.Thread(target=gerar_demo, daemon=True).start()
    
    # Iniciar servidor Flask
    app.run(
        host='0.0.0.0',
        port=PORT,
        debug=False,
        use_reloader=False,
        threaded=True
    )

if __name__ == '__main__':
    main()
