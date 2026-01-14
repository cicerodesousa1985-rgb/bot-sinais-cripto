import os
import time
import threading
import requests
import json
import hashlib
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from flask import Flask, render_template_string, jsonify, request
import logging
from collections import deque
import talib
import warnings
warnings.filterwarnings('ignore')

# =========================
# CONFIGURAÇÃO
# =========================
app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Variáveis de ambiente obrigatórias
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
PORT = int(os.getenv("PORT", "10000"))
DB_FILE = "historico_sinais.json"

# Pares com volume e liquidez
PARES = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "AVAX", "DOT", "MATIC", "DOGE"]

# Timeframes para análise
TIMEFRAMES = ["5m", "15m", "1h", "4h"]

# Variável global para tempo de início
start_time = time.time()

# =========================
# FUNÇÕES DE ANÁLISE TÉCNICA REAL
# =========================
def calcular_indicadores(df):
    """
    Calcula todos os indicadores técnicos para análise
    """
    try:
        # Preços
        close = df['close'].values
        high = df['high'].values
        low = df['low'].values
        volume = df['volume'].values
        
        # 1. TENDÊNCIA
        # Médias Móveis
        df['SMA_20'] = talib.SMA(close, timeperiod=20)
        df['SMA_50'] = talib.SMA(close, timeperiod=50)
        df['EMA_12'] = talib.EMA(close, timeperiod=12)
        df['EMA_26'] = talib.EMA(close, timeperiod=26)
        
        # 2. MOMENTO
        # RSI
        df['RSI'] = talib.RSI(close, timeperiod=14)
        
        # MACD
        df['MACD'], df['MACD_signal'], df['MACD_hist'] = talib.MACD(
            close, fastperiod=12, slowperiod=26, signalperiod=9
        )
        
        # Estocástico
        df['STOCH_K'], df['STOCH_D'] = talib.STOCH(
            high, low, close,
            fastk_period=14, slowk_period=3, slowk_matype=0,
            slowd_period=3, slowd_matype=0
        )
        
        # 3. VOLATILIDADE
        # Bollinger Bands
        df['BB_upper'], df['BB_middle'], df['BB_lower'] = talib.BBANDS(
            close, timeperiod=20, nbdevup=2, nbdevdn=2, matype=0
        )
        
        # ATR (Average True Range)
        df['ATR'] = talib.ATR(high, low, close, timeperiod=14)
        
        # 4. VOLUME
        # Volume + preço
        df['OBV'] = talib.OBV(close, volume)
        
        # MFI (Money Flow Index)
        df['MFI'] = talib.MFI(high, low, close, volume, timeperiod=14)
        
        # 5. MOMENTO ADICIONAL
        # CCI (Commodity Channel Index)
        df['CCI'] = talib.CCI(high, low, close, timeperiod=20)
        
        # Williams %R
        df['WILLR'] = talib.WILLR(high, low, close, timeperiod=14)
        
        # 6. PADRÕES DE CANDLE
        # Padrões de reversão (último candle)
        df['CDL_DOJI'] = talib.CDLDOJI(open=df['open'], high=high, low=low, close=close)
        df['CDL_HAMMER'] = talib.CDLHAMMER(open=df['open'], high=high, low=low, close=close)
        df['CDL_ENGULFING'] = talib.CDLENGULFING(open=df['open'], high=high, low=low, close=close)
        
        return df
    
    except Exception as e:
        logger.error(f"Erro ao calcular indicadores: {e}")
        return df

def analisar_sinal(df):
    """
    Análise técnica REAL para determinar sinal de COMPRA/VENDA
    Retorna: direção, confiança, motivo
    """
    if len(df) < 50:  # Precisa de dados suficientes
        return None, 0, "Dados insuficientes"
    
    try:
        # Últimos valores
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        # Pontuação para cada categoria
        pontos_compra = 0
        pontos_venda = 0
        motivos = []
        
        # 1. TENDÊNCIA (Médias Móveis)
        if not pd.isna(last['SMA_20']) and not pd.isna(last['SMA_50']):
            if last['SMA_20'] > last['SMA_50']:  # Tendência de alta
                pontos_compra += 2
                motivos.append("Tendência ↑")
            else:
                pontos_venda += 2
                motivos.append("Tendência ↓")
        
        # 2. MOMENTO (RSI)
        if not pd.isna(last['RSI']):
            if last['RSI'] < 30:  # Sobre-vendido
                pontos_compra += 3
                motivos.append(f"RSI {last['RSI']:.1f} (Oversold)")
            elif last['RSI'] > 70:  # Sobre-comprado
                pontos_venda += 3
                motivos.append(f"RSI {last['RSI']:.1f} (Overbought)")
            elif 30 <= last['RSI'] <= 50:
                pontos_compra += 1
            elif 50 <= last['RSI'] <= 70:
                pontos_venda += 1
        
        # 3. MACD
        if not pd.isna(last['MACD']) and not pd.isna(last['MACD_signal']):
            if last['MACD'] > last['MACD_signal'] and prev['MACD'] <= prev['MACD_signal']:
                pontos_compra += 2  # Cruzamento de alta
                motivos.append("MACD ↑")
            elif last['MACD'] < last['MACD_signal'] and prev['MACD'] >= prev['MACD_signal']:
                pontos_venda += 2  # Cruzamento de baixa
                motivos.append("MACD ↓")
        
        # 4. BOLLINGER BANDS
        if not pd.isna(last['BB_lower']) and not pd.isna(last['BB_upper']):
            bb_position = (last['close'] - last['BB_lower']) / (last['BB_upper'] - last['BB_lower'])
            if bb_position < 0.2:  # Perto da banda inferior
                pontos_compra += 2
                motivos.append("BB Low")
            elif bb_position > 0.8:  # Perto da banda superior
                pontos_venda += 2
                motivos.append("BB High")
        
        # 5. VOLUME (OBV)
        if not pd.isna(last['OBV']) and not pd.isna(prev['OBV']):
            if last['OBV'] > prev['OBV']:
                pontos_compra += 1
            else:
                pontos_venda += 1
        
        # 6. MFI (Money Flow Index)
        if not pd.isna(last['MFI']):
            if last['MFI'] < 20:
                pontos_compra += 2
                motivos.append(f"MFI {last['MFI']:.1f}")
            elif last['MFI'] > 80:
                pontos_venda += 2
                motivos.append(f"MFI {last['MFI']:.1f}")
        
        # 7. PADRÕES DE CANDLE
        if last['CDL_HAMMER'] > 0:
            pontos_compra += 3
            motivos.append("Padrão Hammer")
        if last['CDL_ENGULFING'] > 0 and last['close'] > last['open']:
            pontos_compra += 3
            motivos.append("Bullish Engulfing")
        elif last['CDL_ENGULFING'] > 0 and last['close'] < last['open']:
            pontos_venda += 3
            motivos.append("Bearish Engulfing")
        
        # 8. STOCHASTIC
        if not pd.isna(last['STOCH_K']) and not pd.isna(last['STOCH_D']):
            if last['STOCH_K'] < 20 and last['STOCH_D'] < 20:
                pontos_compra += 2
                motivos.append("Stoch Oversold")
            elif last['STOCH_K'] > 80 and last['STOCH_D'] > 80:
                pontos_venda += 2
                motivos.append("Stoch Overbought")
        
        # 9. CCI
        if not pd.isna(last['CCI']):
            if last['CCI'] < -100:
                pontos_compra += 2
                motivos.append(f"CCI {last['CCI']:.1f}")
            elif last['CCI'] > 100:
                pontos_venda += 2
                motivos.append(f"CCI {last['CCI']:.1f}")
        
        # Determinar direção
        total_pontos = pontos_compra + pontos_venda
        if total_pontos == 0:
            return None, 0, "Sem sinal claro"
        
        if pontos_compra > pontos_venda:
            confianca = min(95, int((pontos_compra / total_pontos) * 100))
            return "COMPRA", confianca, " | ".join(motivos[:3])
        elif pontos_venda > pontos_compra:
            confianca = min(95, int((pontos_venda / total_pontos) * 100))
            return "VENDA", confianca, " | ".join(motivos[:3])
        else:
            return None, 0, "Empate técnico"
    
    except Exception as e:
        logger.error(f"Erro na análise: {e}")
        return None, 0, f"Erro: {str(e)}"

def buscar_dados_historicos(simbolo, timeframe="15m", limit=100):
    """
    Busca dados históricos da Binance
    """
    try:
        # Converter timeframe para intervalo da Binance
        interval_map = {
            "5m": "5m",
            "15m": "15m", 
            "1h": "1h",
            "4h": "4h",
            "1d": "1d"
        }
        
        interval = interval_map.get(timeframe, "15m")
        url = f"https://api.binance.com/api/v3/klines"
        
        params = {
            "symbol": f"{simbolo}USDT",
            "interval": interval,
            "limit": limit
        }
        
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if not isinstance(data, list):
            logger.error(f"Dados inválidos para {simbolo}: {data}")
            return None
        
        # Converter para DataFrame
        df = pd.DataFrame(data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])
        
        # Converter tipos
        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        df[numeric_cols] = df[numeric_cols].astype(float)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    
    except Exception as e:
        logger.error(f"Erro ao buscar dados de {simbolo}: {e}")
        return None

def calcular_suporte_resistencia(df, window=20):
    """
    Calcula níveis de suporte e resistência
    """
    try:
        highs = df['high'].rolling(window=window).max()
        lows = df['low'].rolling(window=window).min()
        
        # Últimos níveis
        resistencia = highs.iloc[-1]
        suporte = lows.iloc[-1]
        
        return suporte, resistencia
    except:
        return None, None

def get_market_sentiment():
    """Obtém o sentimento do mercado real"""
    try:
        # Fear & Greed Index
        res = requests.get("https://api.alternative.me/fng/", timeout=10).json()
        val = int(res['data'][0]['value'])
        
        # Traduções
        if val >= 75:
            status = "GANÂNCIA EXTREMA"
        elif val >= 55:
            status = "GANÂNCIA"
        elif val >= 45:
            status = "NEUTRO"
        elif val >= 25:
            status = "MEDO"
        else:
            status = "MEDO EXTREMO"
        
        return status, f"Fear & Greed: {val} ({status})"
    except:
        return "NEUTRO", "Sem dados"

def calcular_risco_recompensa(preco_atual, direcao, suporte, resistencia, atr):
    """
    Calcula TP e SL baseado em análise técnica real
    """
    try:
        if direcao == "COMPRA":
            # TP: Resistência ou ATR-based
            if resistencia and resistencia > preco_atual:
                tp = resistencia
            else:
                tp = preco_atual * (1 + (3 * atr / preco_atual))
            
            # SL: Suporte ou ATR-based
            if suporte and suporte < preco_atual:
                sl = suporte
            else:
                sl = preco_atual * (1 - (2 * atr / preco_atual))
        
        else:  # VENDA
            # TP: Suporte ou ATR-based
            if suporte and suporte < preco_atual:
                tp = suporte
            else:
                tp = preco_atual * (1 - (3 * atr / preco_atual))
            
            # SL: Resistência ou ATR-based
            if resistencia and resistencia > preco_atual:
                sl = resistencia
            else:
                sl = preco_atual * (1 + (2 * atr / preco_atual))
        
        # Garantir valores razoáveis
        risco_recompensa = abs(tp - preco_atual) / abs(sl - preco_atual)
        
        if risco_recompensa < 1:
            # Ajustar para RR mínimo de 1.5
            if direcao == "COMPRA":
                tp = preco_atual + (1.5 * abs(preco_atual - sl))
            else:
                tp = preco_atual - (1.5 * abs(sl - preco_atual))
        
        return round(tp, 4), round(sl, 4), round(risco_recompensa, 2)
    
    except Exception as e:
        logger.error(f"Erro cálculo RR: {e}")
        # Fallback
        if direcao == "COMPRA":
            return round(preco_atual * 1.03, 4), round(preco_atual * 0.98, 4), 1.5
        else:
            return round(preco_atual * 0.97, 4), round(preco_atual * 1.02, 4), 1.5

# =========================
# BANCO DE DADOS
# =========================
def carregar_historico():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"sinais": [], "stats": {"total": 0, "acertos": 0, "erros": 0}}

def salvar_historico(dados):
    try:
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
    except:
        pass

# =========================
# BOT PRINCIPAL
# =========================
class BotAnaliseReal:
    def __init__(self):
        db = carregar_historico()
        self.sinais = deque(db.get("sinais", []), maxlen=100)
        self.stats = db.get("stats", {"total": 0, "acertos": 0, "erros": 0})
        self.sentiment, self.sentiment_msg = get_market_sentiment()
        self.winrate = 0
        self.calcular_winrate()
    
    def calcular_winrate(self):
        if self.stats["total"] > 0:
            self.winrate = (self.stats["acertos"] / self.stats["total"]) * 100
        else:
            self.winrate = 0
    
    def analisar_par(self, simbolo, timeframe="15m"):
        """
        Análise técnica completa de um par
        """
        logger.info(f"Analisando {simbolo} no timeframe {timeframe}...")
        
        # 1. Buscar dados históricos
        df = buscar_dados_historicos(simbolo, timeframe, limit=100)
        if df is None or len(df) < 50:
            logger.warning(f"Dados insuficientes para {simbolo}")
            return None
        
        # 2. Calcular indicadores
        df = calcular_indicadores(df)
        if df is None:
            return None
        
        # 3. Analisar sinal
        direcao, confianca, motivo = analisar_sinal(df)
        if direcao is None or confianca < 60:
            logger.info(f"Sem sinal forte para {simbolo} (conf: {confianca})")
            return None
        
        # 4. Preço atual
        preco_atual = df['close'].iloc[-1]
        
        # 5. Calcular suporte/resistência
        suporte, resistencia = calcular_suporte_resistencia(df)
        
        # 6. Calcular ATR para volatilidade
        atr = df['ATR'].iloc[-1] if 'ATR' in df and not pd.isna(df['ATR'].iloc[-1]) else preco_atual * 0.02
        
        # 7. Calcular TP e SL
        tp, sl, rr = calcular_risco_recompensa(preco_atual, direcao, suporte, resistencia, atr)
        
        # 8. Montar sinal
        sinal = {
            "id": int(time.time()),
            "simbolo": f"{simbolo}USDT",
            "direcao": direcao,
            "preco": round(preco_atual, 4),
            "tp": tp,
            "sl": sl,
            "rr": rr,
            "confianca": confianca,
            "timeframe": timeframe,
            "sentimento": self.sentiment,
            "tempo": datetime.now().strftime("%H:%M:%S"),
            "data": datetime.now().strftime("%d/%m/%Y"),
            "motivo": motivo,
            "indicadores": {
                "rsi": round(float(df['RSI'].iloc[-1]), 2) if 'RSI' in df else 0,
                "macd": round(float(df['MACD'].iloc[-1]), 4) if 'MACD' in df else 0,
                "bb_position": round((preco_atual - df['BB_lower'].iloc[-1]) / 
                                   (df['BB_upper'].iloc[-1] - df['BB_lower'].iloc[-1]), 2) 
                            if 'BB_lower' in df and 'BB_upper' in df else 0,
                "volume": round(float(df['volume'].iloc[-1]), 2),
                "suporte": round(suporte, 4) if suporte else 0,
                "resistencia": round(resistencia, 4) if resistencia else 0
            }
        }
        
        logger.info(f"Sinal gerado para {simbolo}: {direcao} a ${preco_atual} (conf: {confianca}%)")
        return sinal
    
    def buscar_melhor_sinal(self):
        """
        Analisa todos os pares e retorna o melhor sinal
        """
        melhores_sinais = []
        
        for simbolo in PARES:
            for timeframe in TIMEFRAMES:
                try:
                    sinal = self.analisar_par(simbolo, timeframe)
                    if sinal and sinal['confianca'] >= 70:
                        melhores_sinais.append(sinal)
                        # Limitar análise por par
                        break
                except Exception as e:
                    logger.error(f"Erro analisando {simbolo}: {e}")
                    continue
        
        if not melhores_sinais:
            logger.info("Nenhum sinal forte encontrado")
            return None
        
        # Selecionar o sinal com maior confiança
        melhor_sinal = max(melhores_sinais, key=lambda x: x['confianca'])
        return melhor_sinal
    
    def gerar_sinal(self):
        """
        Gera um novo sinal com análise real
        """
        try:
            # Atualizar sentimento do mercado
            self.sentiment, self.sentiment_msg = get_market_sentiment()
            
            # Buscar melhor sinal
            sinal = self.buscar_melhor_sinal()
            
            if sinal is None:
                logger.info("Nenhum sinal encontrado com confiança suficiente")
                return None
            
            # Adicionar ao histórico
            self.sinais.append(sinal)
            self.stats["total"] += 1
            
            # Atualizar winrate
            self.calcular_winrate()
            
            # Salvar no banco de dados
            salvar_historico({
                "sinais": list(self.sinais),
                "stats": self.stats
            })
            
            # Enviar para Telegram
            if TELEGRAM_TOKEN and CHAT_ID:
                self.enviar_sinal_telegram(sinal)
            
            logger.info(f"Sinal {sinal['id']} processado: {sinal['simbolo']} {sinal['direcao']}")
            return sinal
            
        except Exception as e:
            logger.error(f"Erro ao gerar sinal: {e}")
            return None
    
    def enviar_sinal_telegram(self, sinal):
        """Envia sinal formatado para o Telegram"""
        try:
            emoji = "🚀" if sinal['direcao'] == "COMPRA" else "🔻"
            
            msg = f"""
{emoji} *ANÁLISE TÉCNICA CONFIRMADA*

💰 *PAR:* {sinal['simbolo']}
📈 *DIREÇÃO:* {sinal['direcao']}
🎯 *ENTRADA:* `${sinal['preco']}`
✅ *TAKE PROFIT:* `${sinal['tp']}` (+{abs(round((sinal['tp']/sinal['preco']-1)*100, 2))}%)
🛑 *STOP LOSS:* `${sinal['sl']}` (-{abs(round((sinal['sl']/sinal['preco']-1)*100, 2))}%)
📊 *RISCO/RECOMPENSA:* 1:{sinal['rr']}

📈 *CONFIANÇA:* {sinal['confianca']}%
⏰ *TIMEFRAME:* {sinal['timeframe']}
🧠 *SENTIMENTO:* {sinal['sentimento']}
📝 *MOTIVO:* {sinal['motivo']}

*INDICADORES:*
• RSI: {sinal['indicadores']['rsi']}
• MACD: {sinal['indicadores']['macd']}
• BB Pos: {sinal['indicadores']['bb_position']}
• Suporte: ${sinal['indicadores']['suporte']}
• Resistência: ${sinal['indicadores']['resistencia']}

⏰ *HORÁRIO:* {sinal['tempo']} | {sinal['data']}
*Win Rate Atual:* {self.winrate:.1f}%
*Sinal ID:* #{sinal['id']}
"""
            
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            response = requests.post(url, json={
                "chat_id": CHAT_ID,
                "text": msg,
                "parse_mode": "Markdown"
            }, timeout=10)
            
            if response.status_code == 200:
                logger.info("Sinal enviado para Telegram")
            else:
                logger.error(f"Erro Telegram: {response.text}")
                
        except Exception as e:
            logger.error(f"Erro ao enviar Telegram: {e}")

# Instância global do bot
bot = BotAnaliseReal()

# =========================
# THREAD DO BOT
# =========================
def loop_bot():
    """Loop principal do bot"""
    logger.info("Iniciando bot de análise técnica real...")
    time.sleep(10)
    
    while True:
        try:
            # Intervalo baseado no mercado (5-15 minutos)
            intervalo = random.randint(300, 900)
            logger.info(f"Próxima análise em {intervalo//60} minutos")
            
            # Gerar sinal com análise real
            sinal = bot.gerar_sinal()
            
            if sinal:
                logger.info(f"Sinal {sinal['id']} - {sinal['simbolo']} {sinal['direcao']} "
                           f"(Conf: {sinal['confianca']}%, RR: 1:{sinal['rr']})")
            
            time.sleep(intervalo)
            
        except KeyboardInterrupt:
            logger.info("Bot interrompido")
            break
        except Exception as e:
            logger.error(f"Erro no loop: {e}")
            time.sleep(60)

# =========================
# DASHBOARD HTML (ATUALIZADO)
# =========================
DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <title>Análise Técnica Real - Crypto Signals</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --primary: #2E86C1;
            --success: #28B463;
            --danger: #E74C3C;
            --warning: #F39C12;
            --dark: #1B2631;
            --darker: #0D1117;
        }
        body { 
            background: linear-gradient(135deg, #0D1117 0%, #1B2631 100%);
            color: #ECF0F1;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            min-height: 100vh;
        }
        .glass-card {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 15px;
            padding: 20px;
            transition: all 0.3s ease;
        }
        .glass-card:hover {
            transform: translateY(-5px);
            border-color: var(--primary);
            box-shadow: 0 10px 20px rgba(0, 0, 0, 0.3);
        }
        .signal-card {
            border-left: 4px solid;
            background: rgba(0, 0, 0, 0.3);
            margin-bottom: 15px;
        }
        .signal-buy { border-color: var(--success); }
        .signal-sell { border-color: var(--danger); }
        .indicator-badge {
            font-size: 0.75rem;
            padding: 3px 8px;
            margin-right: 5px;
            border-radius: 10px;
        }
        .rsi-low { background: rgba(40, 180, 99, 0.2); color: #28B463; }
        .rsi-high { background: rgba(231, 76, 60, 0.2); color: #E74C3C; }
        .bb-low { background: rgba(52, 152, 219, 0.2); color: #3498DB; }
        .bb-high { background: rgba(155, 89, 182, 0.2); color: #9B59B6; }
        .nav-gradient {
            background: linear-gradient(90deg, var(--darker) 0%, var(--dark) 100%);
            border-bottom: 2px solid var(--primary);
        }
        .stat-number {
            font-size: 2.5rem;
            font-weight: 800;
            background: linear-gradient(45deg, var(--primary), var(--warning));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .progress-thin {
            height: 6px;
            border-radius: 3px;
        }
    </style>
</head>
<body>
    <!-- Navbar -->
    <nav class="navbar navbar-expand-lg navbar-dark nav-gradient py-3">
        <div class="container">
            <a class="navbar-brand fw-bold" href="#">
                <i class="fas fa-chart-line me-2"></i>
                ANÁLISE TÉCNICA REAL
            </a>
            <div class="d-flex align-items-center">
                <span class="badge bg-primary me-3">
                    <i class="fas fa-brain me-1"></i> IA ATIVA
                </span>
                <small class="text-muted">
                    <i class="fas fa-sync-alt me-1"></i> 
                    Atualiza em <span id="countdown">30</span>s
                </small>
            </div>
        </div>
    </nav>

    <div class="container mt-4">
        <!-- Header Stats -->
        <div class="row g-4 mb-4">
            <div class="col-md-3">
                <div class="glass-card text-center">
                    <div class="text-muted mb-2">
                        <i class="fas fa-bullseye me-1"></i> WIN RATE
                    </div>
                    <div class="stat-number">{{ "%.1f"|format(bot.winrate) }}%</div>
                    <div class="progress progress-thin mt-2">
                        <div class="progress-bar bg-success" 
                             style="width: {{ bot.winrate }}%"></div>
                    </div>
                </div>
            </div>
            
            <div class="col-md-3">
                <div class="glass-card text-center">
                    <div class="text-muted mb-2">
                        <i class="fas fa-signal me-1"></i> SINAIS HOJE
                    </div>
                    <div class="stat-number">{{ sinais_hoje }}</div>
                    <small class="text-muted">{{ bot.stats.total }} totais</small>
                </div>
            </div>
            
            <div class="col-md-3">
                <div class="glass-card text-center">
                    <div class="text-muted mb-2">
                        <i class="fas fa-chart-bar me-1"></i> SENTIMENTO
                    </div>
                    <div class="h4 fw-bold">{{ bot.sentiment }}</div>
                    <small class="text-primary">{{ bot.sentiment_msg }}</small>
                </div>
            </div>
            
            <div class="col-md-3">
                <div class="glass-card text-center">
                    <div class="text-muted mb-2">
                        <i class="fas fa-cogs me-1"></i> STATUS
                    </div>
                    <div class="h4 fw-bold text-success">ANALISANDO</div>
                    <small class="text-muted">10 pares • 4 timeframes</small>
                </div>
            </div>
        </div>

        <!-- Alertas de Análise -->
        <div class="alert glass-card border-start border-primary">
            <div class="d-flex align-items-center">
                <i class="fas fa-robot text-primary fs-4 me-3"></i>
                <div>
                    <strong>Sistema de Análise Técnica Ativo</strong>
                    <div class="text-muted small">
                        Analisando RSI, MACD, Bollinger Bands, Volume, Suporte/Resistência
                        • Próxima análise: <span id="next-analysis">5 min</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Últimos Sinais -->
        <div class="row">
            <div class="col-12">
                <h4 class="fw-bold mb-3">
                    <i class="fas fa-bolt text-warning me-2"></i>
                    SINAIS RECENTES
                    <span class="badge bg-dark ms-2">{{ sinais|length }} encontrados</span>
                </h4>
                
                {% if sinais %}
                    {% for s in sinais %}
                    <div class="signal-card glass-card {{ 'signal-buy' if s.direcao == 'COMPRA' else 'signal-sell' }}">
                        <div class="row align-items-center">
                            <div class="col-md-8">
                                <div class="d-flex align-items-center mb-2">
                                    <h5 class="fw-bold mb-0 me-3">{{ s.simbolo }}</h5>
                                    <span class="badge {{ 'bg-success' if s.direcao == 'COMPRA' else 'bg-danger' }} me-2">
                                        {{ s.direcao }}
                                    </span>
                                    <span class="badge bg-dark me-2">
                                        {{ s.timeframe }}
                                    </span>
                                    <span class="badge bg-primary">
                                        Conf: {{ s.confianca }}%
                                    </span>
                                </div>
                                
                                <div class="row g-3 mb-2">
                                    <div class="col-sm-3">
                                        <small class="text-muted">ENTRADA</small>
                                        <div class="h6 fw-bold">${{ s.preco }}</div>
                                    </div>
                                    <div class="col-sm-3">
                                        <small class="text-muted">
                                            <i class="fas fa-arrow-up text-success"></i> TP
                                        </small>
                                        <div class="h6 fw-bold text-success">${{ s.tp }}</div>
                                        <small class="text-success">
                                            +{{ "%.2f"|format(((s.tp/s.preco)-1)*100) }}%
                                        </small>
                                    </div>
                                    <div class="col-sm-3">
                                        <small class="text-muted">
                                            <i class="fas fa-arrow-down text-danger"></i> SL
                                        </small>
                                        <div class="h6 fw-bold text-danger">${{ s.sl }}</div>
                                        <small class="text-danger">
                                            -{{ "%.2f"|format(abs((s.sl/s.preco)-1)*100) }}%
                                        </small>
                                    </div>
                                    <div class="col-sm-3">
                                        <small class="text-muted">RISCO/RECOMPENSA</small>
                                        <div class="h6 fw-bold text-info">1:{{ s.rr }}</div>
                                    </div>
                                </div>
                                
                                <div class="mb-2">
                                    <small class="text-muted">INDICADORES:</small>
                                    <div>
                                        {% if s.indicadores.rsi < 30 %}
                                        <span class="indicator-badge rsi-low">
                                            RSI {{ s.indicadores.rsi }} (OS)
                                        </span>
                                        {% elif s.indicadores.rsi > 70 %}
                                        <span class="indicator-badge rsi-high">
                                            RSI {{ s.indicadores.rsi }} (OB)
                                        </span>
                                        {% endif %}
                                        
                                        {% if s.indicadores.bb_position < 0.2 %}
                                        <span class="indicator-badge bb-low">
                                            BB Low
                                        </span>
                                        {% elif s.indicadores.bb_position > 0.8 %}
                                        <span class="indicator-badge bb-high">
                                            BB High
                                        </span>
                                        {% endif %}
                                        
                                        {% if s.indicadores.macd > 0 %}
                                        <span class="indicator-badge" style="background: rgba(46, 204, 113, 0.2); color: #2ECC71;">
                                            MACD +
                                        </span>
                                        {% else %}
                                        <span class="indicator-badge" style="background: rgba(231, 76, 60, 0.2); color: #E74C3C;">
                                            MACD -
                                        </span>
                                        {% endif %}
                                    </div>
                                </div>
                                
                                <div class="text-muted small">
                                    <i class="fas fa-clock me-1"></i> {{ s.tempo }} • 
                                    <i class="fas fa-calendar me-1"></i> {{ s.data }} • 
                                    ID: #{{ s.id }}
                                </div>
                            </div>
                            
                            <div class="col-md-4">
                                <div class="glass-card bg-dark p-3">
                                    <small class="text-muted d-block mb-2">
                                        <i class="fas fa-lightbulb me-1"></i> ANÁLISE
                                    </small>
                                    <div class="small">{{ s.motivo }}</div>
                                    
                                    <hr class="my-2">
                                    
                                    <div class="row small text-center">
                                        <div class="col-6">
                                            <div class="text-muted">SUPORTE</div>
                                            <div class="fw-bold">${{ s.indicadores.suporte }}</div>
                                        </div>
                                        <div class="col-6">
                                            <div class="text-muted">RESISTÊNCIA</div>
                                            <div class="fw-bold">${{ s.indicadores.resistencia }}</div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    {% endfor %}
                {% else %}
                <div class="text-center py-5 glass-card">
                    <i class="fas fa-chart-line fs-1 text-primary mb-3"></i>
                    <h5 class="text-muted">Analisando mercado...</h5>
                    <p class="text-muted small">O primeiro sinal será gerado em breve</p>
                    <div class="spinner-border text-primary mt-3" role="status">
                        <span class="visually-hidden">Carregando...</span>
                    </div>
                </div>
                {% endif %}
            </div>
        </div>

        <!-- Estatísticas -->
        <div class="row mt-4">
            <div class="col-md-6">
                <div class="glass-card">
                    <h6 class="fw-bold mb-3">
                        <i class="fas fa-chart-pie me-2"></i> DISTRIBUIÇÃO DE SINAIS
                    </h6>
                    <div class="row text-center">
                        <div class="col-6">
                            <div class="display-6 fw-bold text-success">{{ compras }}</div>
                            <div class="text-muted small">COMPRAS</div>
                        </div>
                        <div class="col-6">
                            <div class="display-6 fw-bold text-danger">{{ vendas }}</div>
                            <div class="text-muted small">VENDAS</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="col-md-6">
                <div class="glass-card">
                    <h6 class="fw-bold mb-3">
                        <i class="fas fa-info-circle me-2"></i> INFORMAÇÕES DO SISTEMA
                    </h6>
                    <div class="row small">
                        <div class="col-6">
                            <div class="text-muted">ÚLTIMO SINAL</div>
                            <div class="fw-bold">{{ ultimo_sinal_tempo }}</div>
                        </div>
                        <div class="col-6">
                            <div class="text-muted">ANÁLISES HOJE</div>
                            <div class="fw-bold">{{ total_analises }}</div>
                        </div>
                    </div>
                    <div class="mt-2 small text-muted">
                        <i class="fas fa-microchip me-1"></i>
                        Sistema baseado em análise técnica real com múltiplos indicadores
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Footer -->
    <footer class="mt-5 py-3 text-center text-muted small border-top border-dark">
        <div class="container">
            <div class="row align-items-center">
                <div class="col-md-4">
                    <i class="fas fa-shield-alt me-1"></i> Sistema de Análise Técnica
                </div>
                <div class="col-md-4">
                    Uptime: <span id="uptime">--:--:--</span>
                </div>
                <div class="col-md-4">
                    <i class="fas fa-exclamation-triangle me-1"></i> Apenas para análise educacional
                </div>
            </div>
        </div>
    </footer>

    <script>
        // Countdown para refresh
        let countdown = 30;
        function updateCountdown() {
            countdown--;
            document.getElementById('countdown').textContent = countdown;
            if (countdown <= 0) location.reload();
        }
        setInterval(updateCountdown, 1000);
        
        // Uptime
        let startTime = Date.now();
        function updateUptime() {
            const elapsed = Date.now() - startTime;
            const hours = Math.floor(elapsed / 3600000);
            const minutes = Math.floor((elapsed % 3600000) / 60000);
            const seconds = Math.floor((elapsed % 60000) / 1000);
            document.getElementById('uptime').textContent = 
                `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        }
        setInterval(updateUptime, 1000);
        
        // Próxima análise
        let nextAnalysis = 5;
        function updateNextAnalysis() {
            document.getElementById('next-analysis').textContent = `${nextAnalysis} min`;
            nextAnalysis = nextAnalysis > 1 ? nextAnalysis - 1 : 15;
        }
        setInterval(updateNextAnalysis, 60000);
        updateNextAnalysis();
        
        // Tooltips
        document.addEventListener('DOMContentLoaded', function() {
            var tooltips = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
            tooltips.map(function(tooltip) {
                return new bootstrap.Tooltip(tooltip);
            });
        });
    </script>
    
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

# =========================
# ROTAS FLASK
# =========================
@app.route('/')
def index():
    """Dashboard principal"""
    sinais_list = list(bot.sinais)
    
    # Estatísticas para o template
    compras = len([s for s in sinais_list if s['direcao'] == 'COMPRA'])
    vendas = len([s for s in sinais_list if s['direcao'] == 'VENDA'])
    
    # Sinais hoje
    hoje = datetime.now().strftime("%d/%m/%Y")
    sinais_hoje = len([s for s in sinais_list if s.get('data') == hoje])
    
    # Último sinal
    ultimo_sinal_tempo = sinais_list[-1]['tempo'] if sinais_list else "Nenhum"
    
    return render_template_string(
        DASHBOARD_HTML,
        sinais=sinais_list[-20:],  # Últimos 20 sinais
        bot=bot,
        compras=compras,
        vendas=vendas,
        sinais_hoje=sinais_hoje,
        ultimo_sinal_tempo=ultimo_sinal_tempo,
        total_analises=bot.stats["total"]
    )

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "bot": {
            "sinais_total": len(bot.sinais),
            "winrate": round(bot.winrate, 2),
            "sentiment": bot.sentiment,
            "uptime_seconds": int(time.time() - start_time)
        }
    })

@app.route('/api/sinais')
def api_sinais():
    """API para sinais"""
    return jsonify({
        "total": len(bot.sinais),
        "sinais": list(bot.sinais)[-10:],
        "updated": datetime.now().isoformat()
    })

@app.route('/api/analisar/<simbolo>')
def api_analisar(simbolo):
    """API para analisar um par específico"""
    timeframe = request.args.get('timeframe', '15m')
    
    sinal = bot.analisar_par(simbolo.upper(), timeframe)
    
    if sinal:
        return jsonify({
            "success": True,
            "sinal": sinal
        })
    else:
        return jsonify({
            "success": False,
            "message": "Nenhum sinal forte encontrado"
        })

@app.route('/api/gerar_sinal', methods=['POST'])
def api_gerar_sinal():
    """Gerar sinal manualmente"""
    sinal = bot.gerar_sinal()
    
    if sinal:
        return jsonify({
            "success": True,
            "sinal": sinal,
            "message": "Sinal gerado com análise técnica"
        })
    else:
        return jsonify({
            "success": False,
            "message": "Nenhum sinal forte no momento"
        })

# =========================
# INICIALIZAÇÃO
# =========================
if __name__ == '__main__':
    print("=" * 60)
    print("ANÁLISE TÉCNICA REAL - BOT DE SINAIS")
    print("=" * 60)
    print(f"Pares analisados: {', '.join(PARES)}")
    print(f"Timeframes: {', '.join(TIMEFRAMES)}")
    print(f"Dashboard: http://0.0.0.0:{PORT}")
    print(f"Health check: http://0.0.0.0:{PORT}/health")
    print("=" * 60)
    
    # Iniciar thread do bot
    bot_thread = threading.Thread(
        target=loop_bot,
        daemon=True,
        name="BotAnaliseThread"
    )
    bot_thread.start()
    
    # Iniciar servidor Flask
    app.run(
        host='0.0.0.0',
        port=PORT,
        debug=False,
        threaded=True
    )
