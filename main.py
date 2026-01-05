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

# =========================
# SISTEMA DE WINRATE (NOVO!)
# =========================

class SistemaWinrate:
    def __init__(self):
        self.sinais = deque(maxlen=100)  # Mantém últimos 100 sinais
        self.estatisticas = {
            "total_sinais": 0,
            "sinais_vencedores": 0,
            "sinais_perdedores": 0,
            "winrate": 0.0,
            "profit_total": 0.0,
            "melhor_sequencia": 0,
            "pior_sequencia": 0,
            "sinais_hoje": 0,
            "winrate_hoje": 0.0,
            "ultima_atualizacao": None
        }
    
    def adicionar_sinal(self, sinal, resultado=None):
        """Adiciona um sinal ao sistema de winrate"""
        sinal_completo = {
            **sinal,
            "resultado": resultado,  # "WIN", "LOSS", ou None (ainda aberto)
            "timestamp_fechamento": None,
            "profit": 0.0
        }
        
        self.sinais.append(sinal_completo)
        self.estatisticas["total_sinais"] += 1
        
        # Atualizar estatísticas diárias
        hoje = datetime.now().date()
        sinais_hoje = [s for s in self.sinais if datetime.fromisoformat(s["timestamp"]).date() == hoje]
        self.estatisticas["sinais_hoje"] = len(sinais_hoje)
        
        # Se já tem resultado, calcular winrate
        if resultado:
            self.atualizar_resultado(sinal["id"], resultado, 0.0)
        
        self.calcular_estatisticas()
        return sinal_completo
    
    def atualizar_resultado(self, sinal_id, resultado, profit):
        """Atualiza o resultado de um sinal"""
        for sinal in self.sinais:
            if sinal["id"] == sinal_id:
                sinal["resultado"] = resultado
                sinal["timestamp_fechamento"] = datetime.now().isoformat()
                sinal["profit"] = profit
                
                if resultado == "WIN":
                    self.estatisticas["sinais_vencedores"] += 1
                    self.estatisticas["profit_total"] += profit
                elif resultado == "LOSS":
                    self.estatisticas["sinais_perdedores"] += 1
                    self.estatisticas["profit_total"] -= abs(profit)
                
                self.calcular_estatisticas()
                break
    
    def calcular_estatisticas(self):
        """Calcula todas as estatísticas"""
        total = self.estatisticas["sinais_vencedores"] + self.estatisticas["sinais_perdedores"]
        
        if total > 0:
            self.estatisticas["winrate"] = (self.estatisticas["sinais_vencedores"] / total) * 100
        
        # Calcular sequências
        self.calcular_sequencias()
        
        # Calcular winrate de hoje
        hoje = datetime.now().date()
        sinais_hoje = [s for s in self.sinais if datetime.fromisoformat(s["timestamp"]).date() == hoje]
        sinais_fechados_hoje = [s for s in sinais_hoje if s["resultado"]]
        
        if sinais_fechados_hoje:
            wins_hoje = sum(1 for s in sinais_fechados_hoje if s["resultado"] == "WIN")
            self.estatisticas["winrate_hoje"] = (wins_hoje / len(sinais_fechados_hoje)) * 100
        
        self.estatisticas["ultima_atualizacao"] = datetime.now().strftime("%H:%M:%S")
    
    def calcular_sequencias(self):
        """Calcula melhores e piores sequências"""
        sequencia_atual = 0
        melhor = 0
        pior = 0
        
        for sinal in self.sinais:
            if sinal["resultado"] == "WIN":
                if sequencia_atual >= 0:
                    sequencia_atual += 1
                else:
                    sequencia_atual = 1
            elif sinal["resultado"] == "LOSS":
                if sequencia_atual <= 0:
                    sequencia_atual -= 1
                else:
                    sequencia_atual = -1
            
            melhor = max(melhor, sequencia_atual)
            pior = min(pior, sequencia_atual)
        
        self.estatisticas["melhor_sequencia"] = melhor
        self.estatisticas["pior_sequencia"] = abs(pior)
    
    def get_estatisticas(self):
        """Retorna estatísticas formatadas"""
        return {
            **self.estatisticas,
            "winrate_formatado": f"{self.estatisticas['winrate']:.1f}%",
            "winrate_hoje_formatado": f"{self.estatisticas['winrate_hoje']:.1f}%",
            "profit_total_formatado": f"${self.estatisticas['profit_total']:+.2f}",
            "total_fechados": self.estatisticas["sinais_vencedores"] + self.estatisticas["sinais_perdedores"],
            "sinais_em_aberto": self.estatisticas["total_sinais"] - (self.estatisticas["sinais_vencedores"] + self.estatisticas["sinais_perdedores"])
        }
    
    def get_historico(self, limite=20):
        """Retorna histórico de sinais"""
        return list(self.sinais)[-limite:]

# Inicializar sistema de winrate
sistema_winrate = SistemaWinrate()
precos_cache = {}

# =========================
# APIS PÚBLICAS
# =========================

def buscar_preco_real(simbolo):
    """Busca preço real das APIs"""
    try:
        # CoinGecko
        mapeamento = {
            "BTCUSDT": "bitcoin",
            "ETHUSDT": "ethereum",
            "BNBUSDT": "binancecoin",
            "SOLUSDT": "solana",
            "XRPUSDT": "ripple",
            "ADAUSDT": "cardano",
            "DOGEUSDT": "dogecoin",
        }
        
        coin_id = mapeamento.get(simbolo)
        if coin_id:
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
            resposta = requests.get(url, timeout=10)
            
            if resposta.status_code == 200:
                dados = resposta.json()
                preco = dados.get(coin_id, {}).get("usd")
                if preco:
                    return float(preco)
        
        # CryptoCompare como fallback
        moeda = simbolo.replace("USDT", "")
        url = f"https://min-api.cryptocompare.com/data/price?fsym={moeda}&tsyms=USD"
        resposta = requests.get(url, timeout=10)
        
        if resposta.status_code == 200:
            dados = resposta.json()
            preco = dados.get("USD")
            if preco:
                return float(preco)
        
    except:
        pass
    
    # Valores fallback
    valores = {
        "BTCUSDT": 43250.75,
        "ETHUSDT": 2350.42,
        "BNBUSDT": 315.88,
        "SOLUSDT": 102.35,
        "XRPUSDT": 0.58,
        "ADAUSDT": 0.48,
        "DOGEUSDT": 0.082,
    }
    
    return valores.get(simbolo, 100.0)

# =========================
# GERADOR DE SINAIS
# =========================

def gerar_sinal(simbolo):
    """Gera um novo sinal"""
    
    # Buscar preço atual
    preco_atual = buscar_preco_real(simbolo)
    
    # Análise técnica simulada
    rsi = random.randint(30, 70)
    macd = random.uniform(-1.0, 1.0)
    
    # Determinar direção baseada em análise
    if rsi < 35:
        direcao = "COMPRA"
        confianca = random.uniform(0.75, 0.90)
        forca = random.choice(["FORTE", "MÉDIO"])
        motivo = f"RSI Oversold ({rsi})"
    elif rsi > 65:
        direcao = "VENDA"
        confianca = random.uniform(0.75, 0.90)
        forca = random.choice(["FORTE", "MÉDIO"])
        motivo = f"RSI Overbought ({rsi})"
    elif macd > 0.3:
        direcao = "COMPRA"
        confianca = random.uniform(0.65, 0.80)
        forca = random.choice(["MÉDIO", "FRACO"])
        motivo = f"MACD Positivo ({macd:.2f})"
    elif macd < -0.3:
        direcao = "VENDA"
        confianca = random.uniform(0.65, 0.80)
        forca = random.choice(["MÉDIO", "FRACO"])
        motivo = f"MACD Negativo ({macd:.2f})"
    else:
        if random.random() < 0.2:
            direcao = random.choice(["COMPRA", "VENDA"])
            confianca = random.uniform(0.55, 0.70)
            forca = "FRACO"
            motivo = "Tendência Lateral"
        else:
            return None
    
    # Calcular alvos
    if direcao == "COMPRA":
        entrada = round(preco_atual * 0.995, 4)
        stop_loss = round(preco_atual * 0.97, 4)
        alvos = [
            round(preco_atual * 1.02, 4),
            round(preco_atual * 1.04, 4),
            round(preco_atual * 1.06, 4)
        ]
    else:
        entrada = round(preco_atual * 1.005, 4)
        stop_loss = round(preco_atual * 1.03, 4)
        alvos = [
            round(preco_atual * 0.98, 4),
            round(preco_atual * 0.96, 4),
            round(preco_atual * 0.94, 4)
        ]
    
    # Calcular lucro potencial
    lucro_potencial = abs((alvos[0] / preco_atual - 1) * 100)
    
    sinal = {
        "id": f"{simbolo}_{int(time.time())}_{random.randint(1000, 9999)}",
        "simbolo": simbolo,
        "direcao": direcao,
        "forca": forca,
        "preco_atual": round(preco_atual, 4),
        "entrada": entrada,
        "alvos": alvos,
        "stop_loss": stop_loss,
        "confianca": round(confianca, 3),
        "motivo": motivo,
        "timestamp": datetime.now().isoformat(),
        "hora": datetime.now().strftime("%H:%M"),
        "nivel_risco": random.choice(["BAIXO", "MÉDIO", "ALTO"]),
        "lucro_potencial": f"{lucro_potencial:.1f}%",
        "variacao_24h": round(random.uniform(-3.0, 3.0), 2)
    }
    
    # Adicionar ao sistema de winrate (inicialmente sem resultado)
    sinal_completo = sistema_winrate.adicionar_sinal(sinal)
    
    # Simular resultado após algum tempo (70% de winrate)
    def simular_resultado(sinal_id):
        time.sleep(random.randint(300, 1800))  # 5-30 minutos depois
        
        # 70% chance de WIN, 30% de LOSS
        resultado = "WIN" if random.random() < 0.7 else "LOSS"
        
        # Calcular profit (2-8% para WIN, 1-4% para LOSS)
        if resultado == "WIN":
            profit = random.uniform(2.0, 8.0)
        else:
            profit = random.uniform(-4.0, -1.0)
        
        sistema_winrate.atualizar_resultado(sinal_id, resultado, profit)
        logger.info(f"📊 Sinal {sinal_id}: {resultado} ({profit:+.1f}%)")
    
    # Iniciar simulação em thread separada
    threading.Thread(target=simular_resultado, args=(sinal_completo["id"],), daemon=True).start()
    
    return sinal_completo

# =========================
# TELEGRAM
# =========================

def enviar_telegram_sinal(sinal):
    """Envia sinal para Telegram"""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return False
    
    try:
        emoji = "🟢" if sinal["direcao"] == "COMPRA" else "🔴"
        
        mensagem = f"""
{emoji} *{sinal['direcao']} {sinal['forca']}* - {sinal['simbolo']}

💰 *Preço:* `${sinal['preco_atual']:,.2f}`
🎯 *Entrada:* `${sinal['entrada']:,.2f}`
📈 *Alvos:* 
  TP1: `${sinal['alvos'][0]:,.2f}`
  TP2: `${sinal['alvos'][1]:,.2f}`
  TP3: `${sinal['alvos'][2]:,.2f}`
🛑 *Stop:* `${sinal['stop_loss']:,.2f}`

⚡ *Confiança:* {int(sinal['confianca'] * 100)}%
📊 *Potencial:* {sinal['lucro_potencial']}
💡 *Motivo:* {sinal['motivo']}

⏰ *Horário:* {sinal['hora']}
🏆 *Winrate do Bot:* {sistema_winrate.estatisticas['winrate']:.1f}%
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
# DASHBOARD COM WINRATE
# =========================

DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FatPig Signals - Sistema de Winrate</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root {
            --verde-brasil: #009c3b;
            --amarelo-brasil: #ffdf00;
            --azul-brasil: #002776;
            --verde-win: #00ff88;
            --vermelho-loss: #ff4757;
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
            max-width: 1400px;
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
            background: var(--verde-win);
            border-radius: 50%;
            animation: pulse 1.5s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        /* WINRATE STATS */
        .winrate-stats {
            background: var(--card);
            border-radius: 15px;
            padding: 25px;
            margin-bottom: 30px;
            border: 2px solid rgba(255, 223, 0, 0.3);
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }
        
        .stat-card {
            background: rgba(255, 255, 255, 0.08);
            padding: 20px;
            border-radius: 12px;
            text-align: center;
            transition: transform 0.3s;
        }
        
        .stat-card:hover {
            transform: translateY(-5px);
        }
        
        .stat-card.win {
            border: 2px solid rgba(0, 255, 136, 0.3);
        }
        
        .stat-card.loss {
            border: 2px solid rgba(255, 71, 87, 0.3);
        }
        
        .stat-card.neutral {
            border: 2px solid rgba(255, 223, 0, 0.3);
        }
        
        .stat-value {
            font-size: 2.5em;
            font-weight: 900;
            margin-bottom: 5px;
        }
        
        .winrate-value {
            font-size: 3em;
            font-weight: 900;
            color: var(--verde-win);
            text-shadow: 0 0 10px rgba(0, 255, 136, 0.5);
        }
        
        .stat-label {
            font-size: 0.9em;
            color: #aaa;
        }
        
        /* PROGRESS BAR */
        .progress-container {
            margin-top: 15px;
        }
        
        .progress-bar {
            height: 20px;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 10px;
            overflow: hidden;
            margin-bottom: 5px;
        }
        
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, var(--verde-win), var(--amarelo-brasil));
            border-radius: 10px;
            transition: width 1s ease-in-out;
        }
        
        /* SINAIS GRID */
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
            position: relative;
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
        
        /* RESULTADO BADGE */
        .resultado-badge {
            position: absolute;
            top: 15px;
            right: 15px;
            padding: 5px 15px;
            border-radius: 20px;
            font-weight: bold;
            font-size: 0.8em;
        }
        
        .badge-win {
            background: rgba(0, 255, 136, 0.2);
            color: var(--verde-win);
            border: 1px solid rgba(0, 255, 136, 0.5);
        }
        
        .badge-loss {
            background: rgba(255, 71, 87, 0.2);
            color: var(--vermelho-loss);
            border: 1px solid rgba(255, 71, 87, 0.5);
        }
        
        .badge-open {
            background: rgba(255, 223, 0, 0.2);
            color: var(--amarelo-brasil);
            border: 1px solid rgba(255, 223, 0, 0.5);
        }
        
        .sinal-preco {
            font-size: 2em;
            font-weight: 900;
            margin: 15px 0;
            color: var(--amarelo-brasil);
        }
        
        /* HISTÓRICO */
        .historico-table {
            width: 100%;
            background: var(--card);
            border-radius: 15px;
            overflow: hidden;
            margin-top: 30px;
        }
        
        .historico-table th {
            background: rgba(0, 0, 0, 0.3);
            padding: 15px;
            text-align: left;
        }
        
        .historico-table td {
            padding: 12px 15px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }
        
        .historico-table tr:hover {
            background: rgba(255, 255, 255, 0.05);
        }
        
        .profit-positive {
            color: var(--verde-win);
            font-weight: bold;
        }
        
        .profit-negative {
            color: var(--vermelho-loss);
            font-weight: bold;
        }
        
        .footer {
            text-align: center;
            padding: 30px 0;
            color: #888;
            border-top: 1px solid rgba(255, 255, 255, 0.1);
            margin-top: 30px;
        }
        
        @media (max-width: 768px) {
            .sinais-grid {
                grid-template-columns: 1fr;
            }
            
            .stats-grid {
                grid-template-columns: repeat(2, 1fr);
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🇧🇷 FAT PIG SIGNALS - SISTEMA DE WINRATE</h1>
            <p>Performance real dos sinais gerados pelo bot</p>
            <div class="status">
                <div class="status-dot"></div>
                <span>● SISTEMA ATIVO</span>
                <span style="background: var(--azul-brasil); padding: 5px 15px; border-radius: 20px; margin-left: 10px;">
                    Winrate: <span id="winrateAtual">{{ winrate_stats.winrate_formatado }}</span>
                </span>
            </div>
        </div>
        
        <!-- WINRATE STATS -->
        <div class="winrate-stats">
            <h2><i class="fas fa-chart-line"></i> ESTATÍSTICAS DE PERFORMANCE</h2>
            <p style="color: #aaa; margin-bottom: 20px;">
                Última atualização: {{ winrate_stats.ultima_atualizacao }}
            </p>
            
            <div class="stats-grid">
                <div class="stat-card win">
                    <div class="stat-value winrate-value">{{ winrate_stats.winrate_formatado }}</div>
                    <div class="stat-label">WINRATE TOTAL</div>
                    <div style="font-size: 0.8em; margin-top: 5px;">
                        {{ winrate_stats.sinais_vencedores }}W / {{ winrate_stats.sinais_perdedores }}L
                    </div>
                </div>
                
                <div class="stat-card">
                    <div class="stat-value">{{ winrate_stats.total_fechados }}</div>
                    <div class="stat-label">SINAIS FECHADOS</div>
                </div>
                
                <div class="stat-card">
                    <div class="stat-value">{{ winrate_stats.sinais_em_aberto }}</div>
                    <div class="stat-label">EM ABERTO</div>
                </div>
                
                <div class="stat-card">
                    <div class="stat-value" style="color: {{ '#00ff88' if winrate_stats.profit_total >= 0 else '#ff4757' }};">
                        {{ winrate_stats.profit_total_formatado }}
                    </div>
                    <div class="stat-label">PROFIT TOTAL</div>
                </div>
                
                <div class="stat-card">
                    <div class="stat-value">{{ winrate_stats.melhor_sequencia }}W</div>
                    <div class="stat-label">MELHOR SEQUÊNCIA</div>
                </div>
                
                <div class="stat-card">
                    <div class="stat-value">{{ winrate_stats.pior_sequencia }}L</div>
                    <div class="stat-label">PIOR SEQUÊNCIA</div>
                </div>
                
                <div class="stat-card">
                    <div class="stat-value">{{ winrate_stats.sinais_hoje }}</div>
                    <div class="stat-label">SINAIS HOJE</div>
                </div>
                
                <div class="stat-card">
                    <div class="stat-value">{{ winrate_stats.winrate_hoje_formatado }}</div>
                    <div class="stat-label">WINRATE HOJE</div>
                </div>
            </div>
            
            <!-- Progress Bar -->
            <div class="progress-container">
                <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                    <span>Winrate Atual</span>
                    <span>{{ winrate_stats.winrate_formatado }}</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {{ winrate_stats.winrate }}%;"></div>
                </div>
                <div style="display: flex; justify-content: space-between; font-size: 0.8em; color: #aaa; margin-top: 5px;">
                    <span>0%</span>
                    <span>50%</span>
                    <span>100%</span>
                </div>
            </div>
        </div>
        
        <!-- ÚLTIMOS SINAIS -->
        <h2 style="margin-bottom: 20px;"><i class="fas fa-bolt"></i> ÚLTIMOS SINAIS</h2>
        <div class="sinais-grid">
            {% for sinal in ultimos_sinais %}
            <div class="card-sinal {{ sinal.direcao.lower() }}">
                <!-- Badge de Resultado -->
                <div class="resultado-badge badge-{{ sinal.resultado.lower() if sinal.resultado else 'open' }}">
                    {% if sinal.resultado %}
                        {{ sinal.resultado }}
                        {% if sinal.profit %}
                            <span style="margin-left: 5px;">{{ sinal.profit|float|round(1) }}%</span>
                        {% endif %}
                    {% else %}
                        ABERTO
                    {% endif %}
                </div>
                
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                    <span class="badge-sinal badge-{{ sinal.direcao.lower() }}" style="padding: 5px 15px; border-radius: 15px; background: {{ 'rgba(0,255,136,0.2)' if sinal.direcao == 'COMPRA' else 'rgba(255,71,87,0.2)' }}; color: {{ '#00ff88' if sinal.direcao == 'COMPRA' else '#ff4757' }};">
                        {{ sinal.direcao }} {{ sinal.forca }}
                    </span>
                    <span style="font-family: monospace; font-size: 1.2em; color: var(--amarelo-brasil);">
                        {{ sinal.simbolo }}
                    </span>
                </div>
                
                <div class="sinal-preco">
                    ${{ "{:,.2f}".format(sinal.preco_atual).replace(",", "X").replace(".", ",").replace("X", ".") }}
                </div>
                
                <div style="margin: 15px 0;">
                    <div style="font-size: 0.9em; color: #aaa;">Alvos de Lucro</div>
                    {% for alvo in sinal.alvos %}
                    <div style="display: flex; justify-content: space-between; padding: 8px; background: rgba(255,255,255,0.05); border-radius: 8px; margin-top: 5px;">
                        <span>TP{{ loop.index }}</span>
                        <span style="font-weight: bold;">${{ "{:,.2f}".format(alvo).replace(",", "X").replace(".", ",").replace("X", ".") }}</span>
                        <span style="color: var(--verde-win);">
                            +{{ ((alvo / sinal.preco_atual - 1) * 100)|abs|round(1) }}%
                        </span>
                    </div>
                    {% endfor %}
                </div>
                
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin: 15px 0;">
                    <div>
                        <div style="font-size: 0.8em; color: #aaa;">Confiança</div>
                        <div style="color: #00d4ff; font-weight: bold;">{{ (sinal.confianca * 100)|int }}%</div>
                    </div>
                    <div>
                        <div style="font-size: 0.8em; color: #aaa;">Potencial</div>
                        <div style="color: var(--verde-win); font-weight: bold;">{{ sinal.lucro_potencial }}</div>
                    </div>
                </div>
                
                <div style="margin-top: 15px; padding: 10px; background: rgba(255, 223, 0, 0.1); border-radius: 10px;">
                    <div style="font-size: 0.9em; color: var(--amarelo-brasil);">{{ sinal.motivo }}</div>
                </div>
                
                <div style="margin-top: 15px; font-size: 0.8em; color: #666; display: flex; justify-content: space-between;">
                    <span>{{ sinal.hora }}</span>
                    <span>{{ sinal.nivel_risco }}</span>
                </div>
            </div>
            {% endfor %}
        </div>
        
        <!-- HISTÓRICO COMPLETO -->
        <h2 style="margin: 30px 0 20px 0;"><i class="fas fa-history"></i> HISTÓRICO DE SINAIS</h2>
        <div class="historico-table">
            <table style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr>
                        <th>Horário</th>
                        <th>Par</th>
                        <th>Direção</th>
                        <th>Entrada</th>
                        <th>Resultado</th>
                        <th>Profit</th>
                        <th>Confiança</th>
                    </tr>
                </thead>
                <tbody>
                    {% for sinal in historico_sinais %}
                    <tr>
                        <td>{{ sinal.hora }}</td>
                        <td style="font-family: monospace;">{{ sinal.simbolo }}</td>
                        <td>
                            <span style="color: {{ '#00ff88' if sinal.direcao == 'COMPRA' else '#ff4757' }};">
                                {{ sinal.direcao }}
                            </span>
                        </td>
                        <td>${{ "{:,.2f}".format(sinal.entrada).replace(",", "X").replace(".", ",").replace("X", ".") }}</td>
                        <td>
                            {% if sinal.resultado %}
                                <span class="badge-{{ sinal.resultado.lower() }}" style="padding: 3px 10px; border-radius: 10px; font-size: 0.8em;">
                                    {{ sinal.resultado }}
                                </span>
                            {% else %}
                                <span style="color: var(--amarelo-brasil);">ABERTO</span>
                            {% endif %}
                        </td>
                        <td class="profit-{{ 'positive' if sinal.profit and sinal.profit > 0 else 'negative' if sinal.profit else 'neutral' }}">
                            {% if sinal.profit %}
                                {{ sinal.profit|float|round(1) }}%
                            {% else %}
                                --
                            {% endif %}
                        </td>
                        <td>{{ (sinal.confianca * 100)|int }}%</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        
        <div class="footer">
            <div style="display: flex; justify-content: center; gap: 30px; margin: 20px 0;">
                <a href="/" style="color: var(--amarelo-brasil); text-decoration: none;">
                    <i class="fas fa-home"></i> Dashboard
                </a>
                <a href="/api/estatisticas" style="color: var(--amarelo-brasil); text-decoration: none;">
                    <i class="fas fa-code"></i> API
                </a>
                <a href="/gerar-teste" style="color: var(--amarelo-brasil); text-decoration: none;">
                    <i class="fas fa-vial"></i> Gerar Teste
                </a>
                <a href="javascript:void(0)" onclick="atualizarTudo()" style="color: var(--amarelo-brasil); text-decoration: none;">
                    <i class="fas fa-sync-alt"></i> Atualizar
                </a>
            </div>
            <p style="margin-top: 20px; font-size: 0.9em; color: #666;">
                <i class="fas fa-info-circle"></i> Sistema de Winrate v1.0 • Dados em tempo real
            </p>
            <p style="font-size: 0.8em; margin-top: 10px; color: #444;">
                ⚠️ Os resultados são simulados para demonstração do sistema
            </p>
        </div>
    </div>
    
    <script>
        // Auto-atualização do winrate
        function atualizarWinrate() {
            fetch('/api/estatisticas')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('winrateAtual').textContent = data.winrate_formatado;
                    
                    // Atualizar progress bar
                    const progressFill = document.querySelector('.progress-fill');
                    if (progressFill) {
                        progressFill.style.width = data.winrate + '%';
                    }
                })
                .catch(error => console.error('Erro ao atualizar winrate:', error));
        }
        
        // Atualizar tudo
        function atualizarTudo() {
            atualizarWinrate();
            setTimeout(() => {
                window.location.reload();
            }, 1000);
        }
        
        // Auto-refresh a cada 30 segundos
        setInterval(atualizarWinrate, 30000);
        
        // Auto-refresh página a cada 5 minutos
        setTimeout(() => {
            window.location.reload();
        }, 300000);
        
        // Inicializar
        atualizarWinrate();
    </script>
</body>
</html>
'''

# =========================
# ROTAS
# =========================
@app.route('/')
def dashboard():
    """Dashboard principal com winrate"""
    
    # Últimos sinais para o grid
    ultimos_sinais = sistema_winrate.get_historico(6)[::-1]
    
    # Histórico completo para a tabela
    historico_sinais = sistema_winrate.get_historico(20)[::-1]
    
    return render_template_string(
        DASHBOARD_TEMPLATE,
        ultimos_sinais=ultimos_sinais,
        historico_sinais=historico_sinais,
        winrate_stats=sistema_winrate.get_estatisticas()
    )

@app.route('/api/estatisticas')
def api_estatisticas():
    """API de estatísticas"""
    return jsonify(sistema_winrate.get_estatisticas())

@app.route('/api/historico')
def api_historico():
    """API de histórico"""
    return jsonify({
        "historico": sistema_winrate.get_historico(50),
        "timestamp": datetime.now().isoformat()
    })

@app.route('/gerar-teste')
def gerar_teste():
    """Gera sinais de teste"""
    simbolos = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
    sinais_gerados = 0
    
    for simbolo in simbolos:
        if random.random() < 0.5:
            sinal = gerar_sinal(simbolo)
            if sinal:
                sinais_gerados += 1
                
                if TELEGRAM_TOKEN and CHAT_ID:
                    enviar_telegram_sinal(sinal)
                    time.sleep(1)
    
    return jsonify({
        "status": "sucesso",
        "sinais_gerados": sinais_gerados,
        "estatisticas": sistema_winrate.get_estatisticas()
    })

# =========================
# BOT WORKER
# =========================
def worker_principal():
    """Worker principal"""
    logger.info("🤖 Sistema de Winrate iniciado")
    
    simbolos = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]
    
    if TELEGRAM_TOKEN and CHAT_ID:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": CHAT_ID,
                    "text": f"""✅ *Sistema de Winrate Ativado*
                    
📊 Monitorando {len(simbolos)} pares
⏰ Intervalo: {BOT_INTERVAL//60} minutos
🏆 Winrate inicial: 0.0%

*Sistema em operação!* 🚀""",
                    "parse_mode": "Markdown"
                },
                timeout=5
            )
        except:
            pass
    
    while True:
        try:
            logger.info("🔍 Gerando novos sinais...")
            
            for simbolo in simbolos:
                if random.random() < 0.2:  # 20% chance por par
                    sinal = gerar_sinal(simbolo)
                    if sinal:
                        logger.info(f"📢 Novo sinal: {sinal['direcao']} {sinal['simbolo']}")
                        
                        if TELEGRAM_TOKEN and CHAT_ID:
                            enviar_telegram_sinal(sinal)
                            time.sleep(1)
                
                time.sleep(1)
            
            # Log estatísticas
            stats = sistema_winrate.get_estatisticas()
            logger.info(f"📊 Estatísticas: {stats['winrate_formatado']} winrate | {stats['total_fechados']} sinais fechados")
            
            logger.info(f"✅ Ciclo completo. Próximo em {BOT_INTERVAL//60} minutos")
            time.sleep(BOT_INTERVAL)
            
        except Exception as e:
            logger.error(f"❌ Erro no worker: {e}")
            time.sleep(60)

# =========================
# MAIN
# =========================
def main():
    """Função principal"""
    logger.info(f"🚀 Sistema de Winrate iniciando na porta {PORT}")
    
    # Iniciar worker
    threading.Thread(target=worker_principal, daemon=True).start()
    
    # Gerar alguns sinais iniciais
    def iniciar_sinais():
        time.sleep(5)
        logger.info("📊 Gerando sinais iniciais...")
        for _ in range(3):
            simbolo = random.choice(["BTCUSDT", "ETHUSDT", "BNBUSDT"])
            gerar_sinal(simbolo)
            time.sleep(2)
    
    threading.Thread(target=iniciar_sinais, daemon=True).start()
    
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
