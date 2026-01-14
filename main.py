import os
import time
import threading
import requests
import json
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from flask import Flask, render_template_string, jsonify, request
import logging
from collections import deque
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

# Variáveis de ambiente (usar valores padrão para desenvolvimento)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
PORT = int(os.getenv("PORT", "10000"))
DB_FILE = "historico_sinais.json"

# Pares principais
PARES = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "MATIC", "DOT", "AVAX"]

# Timeframes
TIMEFRAMES = ["15m", "1h", "4h"]

# Variável global para tempo de início
start_time = time.time()

# =========================
# FUNÇÕES DE ANÁLISE TÉCNICA SEM TA-Lib
# =========================

def calcular_rsi(prices, period=14):
    """Calcula RSI sem TA-Lib"""
    if len(prices) < period + 1:
        return np.full(len(prices), 50)
    
    deltas = np.diff(prices)
    seed = deltas[:period]
    
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    
    if down == 0:
        return np.full(len(prices), 100)
    
    rs = up / down
    rsi = np.zeros_like(prices)
    rsi[:period] = 100.0 - 100.0 / (1.0 + rs)
    
    for i in range(period, len(prices)):
        delta = deltas[i-1]
        
        if delta > 0:
            upval = delta
            downval = 0.0
        else:
            upval = 0.0
            downval = -delta
        
        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        
        if down == 0:
            rsi[i] = 100
        else:
            rs = up / down
            rsi[i] = 100.0 - 100.0 / (1.0 + rs)
    
    return rsi

def calcular_media_movel(prices, period):
    """Calcula média móvel simples"""
    return pd.Series(prices).rolling(window=period).mean()

def calcular_bb(prices, period=20, std=2):
    """Calcula Bollinger Bands"""
    sma = calcular_media_movel(prices, period)
    rolling_std = pd.Series(prices).rolling(window=period).std()
    
    upper = sma + (rolling_std * std)
    lower = sma - (rolling_std * std)
    
    return upper.values, sma.values, lower.values

def calcular_macd(prices, fast=12, slow=26, signal=9):
    """Calcula MACD"""
    ema_fast = pd.Series(prices).ewm(span=fast, adjust=False).mean()
    ema_slow = pd.Series(prices).ewm(span=slow, adjust=False).mean()
    
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    
    return macd_line.values, signal_line.values, histogram.values

def calcular_obv(close_prices, volumes):
    """Calcula On-Balance Volume"""
    obv = np.zeros(len(close_prices))
    obv[0] = volumes[0]
    
    for i in range(1, len(close_prices)):
        if close_prices[i] > close_prices[i-1]:
            obv[i] = obv[i-1] + volumes[i]
        elif close_prices[i] < close_prices[i-1]:
            obv[i] = obv[i-1] - volumes[i]
        else:
            obv[i] = obv[i-1]
    
    return obv

def calcular_atr(high, low, close, period=14):
    """Calcula Average True Range"""
    tr = np.zeros(len(high))
    tr[0] = high[0] - low[0]
    
    for i in range(1, len(high)):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i-1])
        lc = abs(low[i] - close[i-1])
        tr[i] = max(hl, hc, lc)
    
    atr = pd.Series(tr).rolling(window=period).mean()
    return atr.values

def calcular_stochastic(high, low, close, k_period=14, d_period=3):
    """Calcula Stochastic Oscillator"""
    lowest_low = pd.Series(low).rolling(window=k_period).min()
    highest_high = pd.Series(high).rolling(window=k_period).max()
    
    stoch_k = 100 * ((close - lowest_low) / (highest_high - lowest_low))
    stoch_d = stoch_k.rolling(window=d_period).mean()
    
    return stoch_k.values, stoch_d.values

def calcular_indicadores(df):
    """Calcula todos os indicadores técnicos"""
    try:
        close = df['close'].values
        high = df['high'].values
        low = df['low'].values
        volume = df['volume'].values
        
        # 1. TENDÊNCIA - Médias Móveis
        df['SMA_20'] = calcular_media_movel(close, 20)
        df['SMA_50'] = calcular_media_movel(close, 50)
        df['EMA_12'] = pd.Series(close).ewm(span=12, adjust=False).mean()
        df['EMA_26'] = pd.Series(close).ewm(span=26, adjust=False).mean()
        
        # 2. MOMENTO - RSI
        df['RSI'] = calcular_rsi(close, 14)
        
        # 3. MACD
        df['MACD'], df['MACD_signal'], df['MACD_hist'] = calcular_macd(close)
        
        # 4. BOLLINGER BANDS
        df['BB_upper'], df['BB_middle'], df['BB_lower'] = calcular_bb(close)
        
        # 5. VOLATILIDADE - ATR
        df['ATR'] = calcular_atr(high, low, close)
        
        # 6. VOLUME - OBV
        df['OBV'] = calcular_obv(close, volume)
        
        # 7. STOCHASTIC
        df['STOCH_K'], df['STOCH_D'] = calcular_stochastic(high, low, close)
        
        # 8. CCI (Commodity Channel Index)
        typical_price = (high + low + close) / 3
        sma_tp = calcular_media_movel(typical_price, 20)
        mean_deviation = pd.Series(abs(typical_price - sma_tp)).rolling(20).mean()
        df['CCI'] = (typical_price - sma_tp) / (0.015 * mean_deviation)
        
        # 9. PADRÕES DE CANDLE SIMPLIFICADOS
        df['CANDLE_SIZE'] = abs(df['close'] - df['open'])
        df['CANDLE_BODY'] = df['close'] - df['open']
        df['UPPER_WICK'] = df['high'] - df[['open', 'close']].max(axis=1)
        df['LOWER_WICK'] = df[['open', 'close']].min(axis=1) - df['low']
        
        # Identificar padrões
        df['IS_HAMMER'] = (df['LOWER_WICK'] > 2 * df['CANDLE_SIZE']) & (df['UPPER_WICK'] < df['CANDLE_SIZE'] * 0.1) & (df['CANDLE_BODY'] > 0)
        df['IS_DOJI'] = (df['CANDLE_SIZE'] / (df['high'] - df['low']) < 0.1)
        
        return df
    
    except Exception as e:
        logger.error(f"Erro ao calcular indicadores: {e}")
        return df

def analisar_sinal(df):
    """Análise técnica para determinar sinal"""
    if len(df) < 50:
        return None, 0, "Dados insuficientes"
    
    try:
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        pontos_compra = 0
        pontos_venda = 0
        motivos = []
        
        # 1. TENDÊNCIA (Médias Móveis)
        if not pd.isna(last['SMA_20']) and not pd.isna(last['SMA_50']):
            if last['SMA_20'] > last['SMA_50']:
                pontos_compra += 2
                motivos.append("Tendência ↑")
            else:
                pontos_venda += 2
                motivos.append("Tendência ↓")
        
        # 2. RSI
        if not pd.isna(last['RSI']):
            if last['RSI'] < 30:
                pontos_compra += 3
                motivos.append(f"RSI {last['RSI']:.1f} (Oversold)")
            elif last['RSI'] > 70:
                pontos_venda += 3
                motivos.append(f"RSI {last['RSI']:.1f} (Overbought)")
            elif 30 <= last['RSI'] <= 50:
                pontos_compra += 1
            elif 50 <= last['RSI'] <= 70:
                pontos_venda += 1
        
        # 3. MACD
        if not pd.isna(last['MACD']) and not pd.isna(last['MACD_signal']):
            if last['MACD'] > last['MACD_signal'] and prev['MACD'] <= prev['MACD_signal']:
                pontos_compra += 2
                motivos.append("MACD ↑")
            elif last['MACD'] < last['MACD_signal'] and prev['MACD'] >= prev['MACD_signal']:
                pontos_venda += 2
                motivos.append("MACD ↓")
        
        # 4. BOLLINGER BANDS
        if not pd.isna(last['BB_lower']) and not pd.isna(last['BB_upper']):
            if last['BB_upper'] - last['BB_lower'] > 0:
                bb_position = (last['close'] - last['BB_lower']) / (last['BB_upper'] - last['BB_lower'])
                if bb_position < 0.2:
                    pontos_compra += 2
                    motivos.append("BB Low")
                elif bb_position > 0.8:
                    pontos_venda += 2
                    motivos.append("BB High")
        
        # 5. STOCHASTIC
        if not pd.isna(last['STOCH_K']) and not pd.isna(last['STOCH_D']):
            if last['STOCH_K'] < 20 and last['STOCH_D'] < 20:
                pontos_compra += 2
                motivos.append("Stoch OS")
            elif last['STOCH_K'] > 80 and last['STOCH_D'] > 80:
                pontos_venda += 2
                motivos.append("Stoch OB")
        
        # 6. CCI
        if not pd.isna(last['CCI']):
            if last['CCI'] < -100:
                pontos_compra += 1
                motivos.append(f"CCI {last['CCI']:.0f}")
            elif last['CCI'] > 100:
                pontos_venda += 1
                motivos.append(f"CCI {last['CCI']:.0f}")
        
        # 7. PADRÕES DE CANDLE
        if last['IS_HAMMER']:
            pontos_compra += 2
            motivos.append("Padrão Hammer")
        
        if last['IS_DOJI']:
            pontos_venda += 1
            motivos.append("Padrão Doji")
        
        # 8. VOLUME (OBV)
        if not pd.isna(last['OBV']) and not pd.isna(prev['OBV']):
            if last['OBV'] > prev['OBV']:
                pontos_compra += 1
            else:
                pontos_venda += 1
        
        # Determinar direção
        total_pontos = pontos_compra + pontos_venda
        if total_pontos == 0:
            return None, 0, "Sem sinal claro"
        
        if pontos_compra > pontos_venda:
            confianca = min(95, int((pontos_compra / total_pontos) * 100))
            if confianca >= 60:
                return "COMPRA", confianca, " | ".join(motivos[:3])
        elif pontos_venda > pontos_compra:
            confianca = min(95, int((pontos_venda / total_pontos) * 100))
            if confianca >= 60:
                return "VENDA", confianca, " | ".join(motivos[:3])
        
        return None, 0, "Sinal fraco"
    
    except Exception as e:
        logger.error(f"Erro na análise: {e}")
        return None, 0, f"Erro: {str(e)}"

def buscar_dados_historicos(simbolo, timeframe="15m", limit=100):
    """Busca dados históricos da Binance"""
    try:
        interval_map = {
            "5m": "5m", "15m": "15m", "1h": "1h", 
            "4h": "4h", "1d": "1d"
        }
        
        interval = interval_map.get(timeframe, "15m")
        url = "https://api.binance.com/api/v3/klines"
        
        params = {
            "symbol": f"{simbolo}USDT",
            "interval": interval,
            "limit": limit
        }
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code != 200:
            # Fallback para API pública alternativa
            url = f"https://api.binance.com/api/v3/ticker/24hr"
            response = requests.get(url, params={"symbol": f"{simbolo}USDT"})
            if response.status_code == 200:
                data = response.json()
                price = float(data['lastPrice'])
                volume = float(data['volume'])
                
                # Criar dataframe mínimo
                now = datetime.now()
                timestamps = [now - timedelta(minutes=i) for i in range(limit)]
                timestamps.reverse()
                
                df = pd.DataFrame({
                    'timestamp': timestamps,
                    'open': [price * (1 - 0.01 * (i/limit)) for i in range(limit)],
                    'high': [price * (1 + 0.02 * (i/limit)) for i in range(limit)],
                    'low': [price * (1 - 0.02 * (i/limit)) for i in range(limit)],
                    'close': [price * (1 - 0.005 * (i/limit)) for i in range(limit)],
                    'volume': [volume * (0.5 + 0.5 * (i/limit)) for i in range(limit)]
                })
                return df
        
        data = response.json()
        
        if not isinstance(data, list):
            return None
        
        df = pd.DataFrame(data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])
        
        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        df[numeric_cols] = df[numeric_cols].astype(float)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    
    except Exception as e:
        logger.error(f"Erro ao buscar dados de {simbolo}: {e}")
        return None

def calcular_suporte_resistencia(df, window=20):
    """Calcula níveis de suporte e resistência"""
    try:
        highs = df['high'].rolling(window=window).max()
        lows = df['low'].rolling(window=window).min()
        
        resistencia = highs.iloc[-1]
        suporte = lows.iloc[-1]
        
        return suporte, resistencia
    except:
        return None, None

def get_market_sentiment():
    """Obtém o sentimento do mercado"""
    try:
        res = requests.get("https://api.alternative.me/fng/", timeout=10).json()
        val = int(res['data'][0]['value'])
        
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
        
        return status, f"Fear & Greed: {val}"
    except:
        return "NEUTRO", "Sem dados"

def calcular_risco_recompensa(preco_atual, direcao, suporte, resistencia, atr):
    """Calcula TP e SL baseado em análise"""
    try:
        if pd.isna(atr) or atr == 0:
            atr = preco_atual * 0.02
        
        if direcao == "COMPRA":
            if resistencia and resistencia > preco_atual:
                tp = resistencia
            else:
                tp = preco_atual * (1 + (3 * atr / preco_atual))
            
            if suporte and suporte < preco_atual:
                sl = suporte
            else:
                sl = preco_atual * (1 - (2 * atr / preco_atual))
        
        else:  # VENDA
            if suporte and suporte < preco_atual:
                tp = suporte
            else:
                tp = preco_atual * (1 - (3 * atr / preco_atual))
            
            if resistencia and resistencia > preco_atual:
                sl = resistencia
            else:
                sl = preco_atual * (1 + (2 * atr / preco_atual))
        
        # Garantir valores válidos
        tp = max(tp, 0.0001)
        sl = max(sl, 0.0001)
        
        risco_recompensa = abs(tp - preco_atual) / abs(sl - preco_atual) if abs(sl - preco_atual) > 0 else 1.5
        
        if risco_recompensa < 1:
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
    except Exception as e:
        logger.error(f"Erro ao salvar histórico: {e}")

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
        """Análise técnica de um par"""
        logger.info(f"Analisando {simbolo} ({timeframe})...")
        
        df = buscar_dados_historicos(simbolo, timeframe, limit=100)
        if df is None or len(df) < 50:
            logger.warning(f"Dados insuficientes para {simbolo}")
            return None
        
        df = calcular_indicadores(df)
        if df is None:
            return None
        
        direcao, confianca, motivo = analisar_sinal(df)
        if direcao is None or confianca < 60:
            logger.info(f"Sem sinal forte para {simbolo} (conf: {confianca})")
            return None
        
        preco_atual = df['close'].iloc[-1]
        suporte, resistencia = calcular_suporte_resistencia(df)
        
        atr = df['ATR'].iloc[-1] if 'ATR' in df and not pd.isna(df['ATR'].iloc[-1]) else preco_atual * 0.02
        tp, sl, rr = calcular_risco_recompensa(preco_atual, direcao, suporte, resistencia, atr)
        
        sinal = {
            "id": int(time.time()),
            "simbolo": f"{simbolo}USDT",
            "direcao": direcao,
            "preco": round(float(preco_atual), 4),
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
                "volume": round(float(df['volume'].iloc[-1]), 2),
                "suporte": round(float(suporte), 4) if suporte else 0,
                "resistencia": round(float(resistencia), 4) if resistencia else 0
            }
        }
        
        logger.info(f"Sinal: {simbolo} {direcao} ${preco_atual} (conf: {confianca}%)")
        return sinal
    
    def buscar_melhor_sinal(self):
        """Analisa todos os pares"""
        melhores_sinais = []
        
        for simbolo in PARES:
            for timeframe in TIMEFRAMES:
                try:
                    sinal = self.analisar_par(simbolo, timeframe)
                    if sinal and sinal['confianca'] >= 65:
                        melhores_sinais.append(sinal)
                        break
                except Exception as e:
                    logger.error(f"Erro analisando {simbolo}: {e}")
                    continue
        
        if not melhores_sinais:
            logger.info("Nenhum sinal forte encontrado")
            return None
        
        melhor_sinal = max(melhores_sinais, key=lambda x: x['confianca'])
        return melhor_sinal
    
    def gerar_sinal(self):
        """Gera um novo sinal"""
        try:
            self.sentiment, self.sentiment_msg = get_market_sentiment()
            sinal = self.buscar_melhor_sinal()
            
            if sinal is None:
                logger.info("Nenhum sinal com confiança suficiente")
                return None
            
            self.sinais.append(sinal)
            self.stats["total"] += 1
            self.calcular_winrate()
            
            salvar_historico({
                "sinais": list(self.sinais),
                "stats": self.stats
            })
            
            if TELEGRAM_TOKEN and CHAT_ID:
                self.enviar_sinal_telegram(sinal)
            
            logger.info(f"Sinal {sinal['id']} processado")
            return sinal
            
        except Exception as e:
            logger.error(f"Erro ao gerar sinal: {e}")
            return None
    
    def enviar_sinal_telegram(self, sinal):
        """Envia sinal para Telegram"""
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
• Suporte: ${sinal['indicadores']['suporte']}
• Resistência: ${sinal['indicadores']['resistencia']}

⏰ *HORÁRIO:* {sinal['tempo']} | {sinal['data']}
*Win Rate:* {self.winrate:.1f}%
*Sinal ID:* #{sinal['id']}
"""
            
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={
                "chat_id": CHAT_ID,
                "text": msg,
                "parse_mode": "Markdown"
            }, timeout=10)
            
            logger.info("Sinal enviado para Telegram")
                
        except Exception as e:
            logger.error(f"Erro Telegram: {e}")

# Instância global do bot
bot = BotAnaliseReal()

# =========================
# THREAD DO BOT
# =========================
def loop_bot():
    """Loop principal"""
    logger.info("Iniciando bot de análise...")
    time.sleep(10)
    
    while True:
        try:
            # Intervalo de 5-15 minutos
            intervalo = 300  # 5 minutos
            logger.info(f"Próxima análise em {intervalo//60} minutos")
            
            sinal = bot.gerar_sinal()
            
            if sinal:
                logger.info(f"Sinal {sinal['id']} - {sinal['simbolo']} {sinal['direcao']}")
            
            time.sleep(intervalo)
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Erro no loop: {e}")
            time.sleep(60)

# =========================
# DASHBOARD SIMPLIFICADO
# =========================
DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <title>Análise Técnica - Crypto Signals</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body { 
            background: #0f172a; 
            color: #e2e8f0;
            font-family: 'Segoe UI', system-ui, sans-serif;
        }
        .card-custom {
            background: rgba(30, 41, 59, 0.7);
            border: 1px solid rgba(148, 163, 184, 0.2);
            border-radius: 12px;
            padding: 20px;
            transition: transform 0.2s;
        }
        .card-custom:hover {
            transform: translateY(-3px);
            border-color: #3b82f6;
        }
        .signal-card {
            border-left: 4px solid;
            margin-bottom: 15px;
        }
        .signal-buy { border-color: #10b981; }
        .signal-sell { border-color: #ef4444; }
        .nav-custom {
            background: #1e293b;
            border-bottom: 2px solid #3b82f6;
        }
        .badge-indicator {
            font-size: 0.75rem;
            padding: 4px 10px;
            border-radius: 20px;
            margin: 2px;
        }
        .text-gradient {
            background: linear-gradient(45deg, #3b82f6, #8b5cf6);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
    </style>
</head>
<body>
    <!-- Navbar -->
    <nav class="navbar navbar-expand-lg navbar-dark nav-custom py-3">
        <div class="container">
            <a class="navbar-brand fw-bold" href="#">
                <i class="fas fa-chart-line me-2 text-gradient"></i>
                CRYPTO SIGNALS
            </a>
            <div class="d-flex align-items-center">
                <span class="badge bg-success me-3">
                    <i class="fas fa-check-circle me-1"></i> ATIVO
                </span>
                <small class="text-muted">
                    <i class="fas fa-sync-alt me-1"></i> 
                    Atualiza em <span id="countdown">30</span>s
                </small>
            </div>
        </div>
    </nav>

    <div class="container mt-4">
        <!-- Stats -->
        <div class="row g-4 mb-4">
            <div class="col-md-3">
                <div class="card-custom text-center">
                    <div class="text-muted mb-2">WIN RATE</div>
                    <div class="h2 fw-bold text-gradient">{{ "%.1f"|format(bot.winrate) }}%</div>
                </div>
            </div>
            
            <div class="col-md-3">
                <div class="card-custom text-center">
                    <div class="text-muted mb-2">SINAIS</div>
                    <div class="h2 fw-bold">{{ bot.stats.total }}</div>
                </div>
            </div>
            
            <div class="col-md-3">
                <div class="card-custom text-center">
                    <div class="text-muted mb-2">SENTIMENTO</div>
                    <div class="h4 fw-bold">{{ bot.sentiment }}</div>
                </div>
            </div>
            
            <div class="col-md-3">
                <div class="card-custom text-center">
                    <div class="text-muted mb-2">STATUS</div>
                    <div class="h4 fw-bold text-success">ANALISANDO</div>
                </div>
            </div>
        </div>

        <!-- Sinais -->
        <h4 class="fw-bold mb-3">
            <i class="fas fa-bolt text-warning me-2"></i>
            ÚLTIMOS SINAIS
        </h4>
        
        {% if sinais %}
            {% for s in sinais %}
            <div class="signal-card card-custom {{ 'signal-buy' if s.direcao == 'COMPRA' else 'signal-sell' }}">
                <div class="row">
                    <div class="col-md-8">
                        <div class="d-flex align-items-center mb-2">
                            <h5 class="fw-bold mb-0 me-3">{{ s.simbolo }}</h5>
                            <span class="badge {{ 'bg-success' if s.direcao == 'COMPRA' else 'bg-danger' }}">
                                {{ s.direcao }}
                            </span>
                            <span class="badge bg-dark ms-2">{{ s.timeframe }}</span>
                            <span class="badge bg-primary ms-2">{{ s.confianca }}%</span>
                        </div>
                        
                        <div class="row g-3 mb-2">
                            <div class="col-sm-4">
                                <small class="text-muted">ENTRADA</small>
                                <div class="h5 fw-bold">${{ s.preco }}</div>
                            </div>
                            <div class="col-sm-4">
                                <small class="text-muted">TP</small>
                                <div class="h5 fw-bold text-success">${{ s.tp }}</div>
                                <small class="text-success">+{{ "%.2f"|format(((s.tp/s.preco)-1)*100) }}%</small>
                            </div>
                            <div class="col-sm-4">
                                <small class="text-muted">SL</small>
                                <div class="h5 fw-bold text-danger">${{ s.sl }}</div>
                                <small class="text-danger">-{{ "%.2f"|format(abs((s.sl/s.preco)-1
