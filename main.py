import telebot
import requests
import pandas as pd
import numpy as np
import time
import schedule
import threading
from flask import Flask, render_template_string, jsonify, request
import os
from datetime import datetime, timedelta
import logging
import talib
from typing import Optional, List, Dict, Tuple
import json
import warnings
warnings.filterwarnings('ignore')

# =========================
# CONFIGURAÇÃO DE LOG
# =========================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('crypto_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# =========================
# CONFIGURAÇÕES
# =========================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

if not TELEGRAM_TOKEN or not CHAT_ID:
    raise ValueError("Configure TELEGRAM_TOKEN e CHAT_ID como variáveis de ambiente")

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode='HTML')

# Estados do bot
signals_paused = False
last_signals = []
signal_cache = {}
bot_start_time = datetime.now()

# =========================
# LISTA EXPANDIDA DE PARES (30+ pares)
# =========================
PAIRS = [
    # Top 10 por market cap
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT',
    'ADAUSDT', 'AVAXUSDT', 'DOGEUSDT', 'DOTUSDT', 'TRXUSDT',
    
    # Mid caps populares
    'LINKUSDT', 'MATICUSDT', 'SHIBUSDT', 'LTCUSDT', 'UNIUSDT',
    'ATOMUSDT', 'ETCUSDT', 'XLMUSDT', 'ALGOUSDT', 'VETUSDT',
    
    # Altcoins promissores
    'FILUSDT', 'ICPUSDT', 'NEARUSDT', 'FTMUSDT', 'AAVEUSDT',
    'APEUSDT', 'GRTUSDT', 'SANDUSDT', 'MANAUSDT', 'AXSUSDT',
    
    # DeFi tokens
    'MKRUSDT', 'SNXUSDT', 'COMPUSDT', 'YFIUSDT', 'CRVUSDT',
    
    # Layer 1 alternatives
    'FTTUSDT', 'EGLDUSDT', 'ONEUSDT', 'HNTUSDT', 'KLAYUSDT',
    
    # Meme coins & trending
    'PEPEUSDT', 'FLOKIUSDT', 'BONKUSDT', 'WIFUSDT'
]

# Agrupa por categoria para melhor organização
PAIR_CATEGORIES = {
    'blue_chips': ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT'],
    'large_caps': ['ADAUSDT', 'AVAXUSDT', 'DOGEUSDT', 'DOTUSDT', 'TRXUSDT', 'LINKUSDT'],
    'mid_caps': ['MATICUSDT', 'SHIBUSDT', 'LTCUSDT', 'UNIUSDT', 'ATOMUSDT', 'ETCUSDT'],
    'defi': ['AAVEUSDT', 'MKRUSDT', 'SNXUSDT', 'COMPUSDT', 'CRVUSDT'],
    'gaming_metaverse': ['SANDUSDT', 'MANAUSDT', 'AXSUSDT', 'GALAUSDT', 'ENJUSDT'],
    'meme_coins': ['PEPEUSDT', 'FLOKIUSDT', 'BONKUSDT', 'WIFUSDT']
}

# =========================
# ESTRATÉGIAS EXPANDIDAS (15+ estratégias)
# =========================
STRATEGIES = {
    # Estratégias de tendência
    'ema_crossover': {'weight': 1.2, 'active': True, 'category': 'trend'},
    'macd_crossover': {'weight': 1.1, 'active': True, 'category': 'trend'},
    'supertrend': {'weight': 1.3, 'active': True, 'category': 'trend'},
    'ichimoku': {'weight': 1.0, 'active': True, 'category': 'trend'},
    'adx_trend': {'weight': 0.9, 'active': True, 'category': 'trend'},
    
    # Estratégias de momentum
    'rsi_divergence': {'weight': 1.1, 'active': True, 'category': 'momentum'},
    'stochastic': {'weight': 0.8, 'active': True, 'category': 'momentum'},
    'cci': {'weight': 0.7, 'active': True, 'category': 'momentum'},
    'mfi': {'weight': 0.9, 'active': True, 'category': 'momentum'},
    'williams_r': {'weight': 0.8, 'active': True, 'category': 'momentum'},
    
    # Estratégias de reversão
    'bollinger_bands': {'weight': 1.0, 'active': True, 'category': 'reversal'},
    'pivot_points': {'weight': 0.9, 'active': True, 'category': 'reversal'},
    'support_resistance': {'weight': 1.1, 'active': True, 'category': 'reversal'},
    
    # Estratégias de volume
    'vwap': {'weight': 1.0, 'active': True, 'category': 'volume'},
    'obv': {'weight': 0.8, 'active': True, 'category': 'volume'},
    'volume_profile': {'weight': 0.9, 'active': True, 'category': 'volume'},
    
    # Estratégias avançadas
    'fractals': {'weight': 0.7, 'active': True, 'category': 'advanced'},
    'harmonics': {'weight': 0.6, 'active': True, 'category': 'advanced'},
    'market_structure': {'weight': 1.2, 'active': True, 'category': 'advanced'}
}

# =========================
# FUNÇÕES UTILITÁRIAS
# =========================
def format_price(price: float, symbol: str) -> str:
    """Formata preço baseado no par"""
    if price >= 1000:
        return f"{price:.1f}"
    elif price >= 100:
        return f"{price:.2f}"
    elif price >= 10:
        return f"{price:.3f}"
    elif price >= 1:
        return f"{price:.4f}"
    else:
        return f"{price:.6f}"

def get_uptime() -> str:
    """Calcula tempo de atividade do bot"""
    uptime = datetime.now() - bot_start_time
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    if days > 0:
        return f"{days}d {hours}h"
    return f"{hours}h {minutes}m"

def get_pair_category(pair: str) -> str:
    """Retorna categoria do par"""
    for category, pairs in PAIR_CATEGORIES.items():
        if pair in pairs:
            return category.replace('_', ' ').title()
    return "Other"

# =========================
# FUNÇÃO PARA DADOS DA BINANCE (OTIMIZADA)
# =========================
def get_binance_data(symbol: str, interval: str = '1m', limit: int = 300) -> Optional[pd.DataFrame]:
    """Obtém dados da Binance com múltiplos intervalos"""
    try:
        url = 'https://api.binance.com/api/v3/klines'
        params = {'symbol': symbol, 'interval': interval, 'limit': limit}
        
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        
        data = response.json()
        
        if not data:
            return None
            
        df = pd.DataFrame(data, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'qav', 'trades', 'tbb', 'tbq', 'ignore'
        ])
        
        # Conversão de tipos
        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        df[numeric_cols] = df[numeric_cols].astype(float)
        df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
        df.set_index('open_time', inplace=True)
        
        return df
        
    except Exception as e:
        logger.error(f"Erro ao obter dados para {symbol}: {e}")
        return None

# =========================
# ESTRATÉGIAS DE TENDÊNCIA (5 estratégias)
# =========================
def ema_crossover_strategy(df: pd.DataFrame) -> Optional[str]:
    """EMA 9/21/50 Crossover"""
    try:
        df['EMA9'] = talib.EMA(df['close'], timeperiod=9)
        df['EMA21'] = talib.EMA(df['close'], timeperiod=21)
        df['EMA50'] = talib.EMA(df['close'], timeperiod=50)
        
        last, prev = df.iloc[-1], df.iloc[-2]
        
        # Golden Cross
        if (last['EMA9'] > last['EMA21'] > last['EMA50'] and 
            (prev['EMA9'] <= prev['EMA21'] or prev['EMA21'] <= prev['EMA50'])):
            return 'buy'
        
        # Death Cross
        if (last['EMA9'] < last['EMA21'] < last['EMA50'] and 
            (prev['EMA9'] >= prev['EMA21'] or prev['EMA21'] >= prev['EMA50'])):
            return 'sell'
            
    except Exception as e:
        logger.error(f"Erro EMA Crossover: {e}")
    return None

def macd_crossover_strategy(df: pd.DataFrame) -> Optional[str]:
    """MACD com múltiplos timeframes"""
    try:
        macd, signal, hist = talib.MACD(df['close'], 
                                        fastperiod=12, 
                                        slowperiod=26, 
                                        signalperiod=9)
        
        df['MACD'] = macd
        df['MACD_SIGNAL'] = signal
        df['MACD_HIST'] = hist
        
        last, prev = df.iloc[-1], df.iloc[-2]
        
        # Bullish crossover
        if (prev['MACD'] < prev['MACD_SIGNAL'] and 
            last['MACD'] > last['MACD_SIGNAL'] and 
            last['MACD_HIST'] > 0):
            return 'buy'
        
        # Bearish crossover
        if (prev['MACD'] > prev['MACD_SIGNAL'] and 
            last['MACD'] < last['MACD_SIGNAL'] and 
            last['MACD_HIST'] < 0):
            return 'sell'
            
    except Exception as e:
        logger.error(f"Erro MACD: {e}")
    return None

def supertrend_strategy(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> Optional[str]:
    """Estratégia SuperTrend"""
    try:
        # Calcula ATR
        atr = talib.ATR(df['high'], df['low'], df['close'], timeperiod=period)
        
        # Calcula bandas SuperTrend
        hl2 = (df['high'] + df['low']) / 2
        upper_band = hl2 + (multiplier * atr)
        lower_band = hl2 - (multiplier * atr)
        
        # Inicializa SuperTrend
        supertrend = pd.Series(index=df.index, dtype=float)
        trend = pd.Series(index=df.index, dtype=int)  # 1 = uptrend, -1 = downtrend
        
        for i in range(1, len(df)):
            if df['close'].iloc[i] > upper_band.iloc[i-1]:
                trend.iloc[i] = 1
                supertrend.iloc[i] = lower_band.iloc[i]
            elif df['close'].iloc[i] < lower_band.iloc[i-1]:
                trend.iloc[i] = -1
                supertrend.iloc[i] = upper_band.iloc[i]
            else:
                trend.iloc[i] = trend.iloc[i-1]
                supertrend.iloc[i] = (lower_band.iloc[i] if trend.iloc[i] == 1 
                                      else upper_band.iloc[i])
        
        # Verifica mudança de tendência
        last, prev = trend.iloc[-1], trend.iloc[-2]
        
        if prev == -1 and last == 1:
            return 'buy'
        elif prev == 1 and last == -1:
            return 'sell'
            
    except Exception as e:
        logger.error(f"Erro SuperTrend: {e}")
    return None

def ichimoku_strategy(df: pd.DataFrame) -> Optional[str]:
    """Estratégia Ichimoku Cloud"""
    try:
        # Calcula componentes Ichimoku
        tenkan_sen = (df['high'].rolling(9).max() + df['low'].rolling(9).min()) / 2
        kijun_sen = (df['high'].rolling(26).max() + df['low'].rolling(26).min()) / 2
        senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(26)
        senkou_span_b = ((df['high'].rolling(52).max() + df['low'].rolling(52).min()) / 2).shift(26)
        
        last_close = df['close'].iloc[-1]
        
        # Sinal de compra: preço acima da nuvem e TK crossover
        if (last_close > senkou_span_a.iloc[-1] and 
            last_close > senkou_span_b.iloc[-1] and
            tenkan_sen.iloc[-1] > kijun_sen.iloc[-1] and
            tenkan_sen.iloc[-2] <= kijun_sen.iloc[-2]):
            return 'buy'
        
        # Sinal de venda: preço abaixo da nuvem e TK crossunder
        if (last_close < senkou_span_a.iloc[-1] and 
            last_close < senkou_span_b.iloc[-1] and
            tenkan_sen.iloc[-1] < kijun_sen.iloc[-1] and
            tenkan_sen.iloc[-2] >= kijun_sen.iloc[-2]):
            return 'sell'
            
    except Exception as e:
        logger.error(f"Erro Ichimoku: {e}")
    return None

def adx_trend_strategy(df: pd.DataFrame, adx_threshold: int = 25) -> Optional[str]:
    """ADX + DI para identificar força da tendência"""
    try:
        adx = talib.ADX(df['high'], df['low'], df['close'], timeperiod=14)
        plus_di = talib.PLUS_DI(df['high'], df['low'], df['close'], timeperiod=14)
        minus_di = talib.MINUS_DI(df['high'], df['low'], df['close'], timeperiod=14)
        
        last_adx = adx.iloc[-1]
        last_plus_di = plus_di.iloc[-1]
        last_minus_di = minus_di.iloc[-1]
        
        # Tendência forte de alta
        if last_adx > adx_threshold and last_plus_di > last_minus_di:
            # Crossover DI
            if (plus_di.iloc[-2] <= minus_di.iloc[-2] and 
                last_plus_di > last_minus_di):
                return 'buy'
        
        # Tendência forte de baixa
        elif last_adx > adx_threshold and last_minus_di > last_plus_di:
            # Crossunder DI
            if (minus_di.iloc[-2] <= plus_di.iloc[-2] and 
                last_minus_di > last_plus_di):
                return 'sell'
                
    except Exception as e:
        logger.error(f"Erro ADX: {e}")
    return None

# =========================
# ESTRATÉGIAS DE MOMENTUM (5 estratégias)
# =========================
def rsi_divergence_strategy(df: pd.DataFrame) -> Optional[str]:
    """RSI com detecção de divergência"""
    try:
        rsi = talib.RSI(df['close'], timeperiod=14)
        df['RSI'] = rsi
        
        # Divergência de alta: preço faz lower low, RSI faz higher low
        if len(df) >= 20:
            # Últimos 10 candles para análise
            prices = df['close'].values[-10:]
            rsi_values = rsi.values[-10:]
            
            # Encontra mínimos locais
            price_lows = []
            rsi_lows = []
            
            for i in range(1, len(prices)-1):
                if prices[i] < prices[i-1] and prices[i] < prices[i+1]:
                    price_lows.append((i, prices[i]))
                if rsi_values[i] < rsi_values[i-1] and rsi_values[i] < rsi_values[i+1]:
                    rsi_lows.append((i, rsi_values[i]))
            
            # Verifica divergência bullish
            if len(price_lows) >= 2 and len(rsi_lows) >= 2:
                if (price_lows[-1][1] < price_lows[-2][1] and 
                    rsi_lows[-1][1] > rsi_lows[-2][1] and
                    rsi_values[-1] < 40):  # RSI oversold
                    return 'buy'
            
            # Verifica divergência bearish
            price_highs = []
            rsi_highs = []
            
            for i in range(1, len(prices)-1):
                if prices[i] > prices[i-1] and prices[i] > prices[i+1]:
                    price_highs.append((i, prices[i]))
                if rsi_values[i] > rsi_values[i-1] and rsi_values[i] > rsi_values[i+1]:
                    rsi_highs.append((i, rsi_values[i]))
            
            if len(price_highs) >= 2 and len(rsi_highs) >= 2:
                if (price_highs[-1][1] > price_highs[-2][1] and 
                    rsi_highs[-1][1] < rsi_highs[-2][1] and
                    rsi_values[-1] > 60):  # RSI overbought
                    return 'sell'
        
        # Sinais básicos de RSI
        last_rsi = rsi.iloc[-1]
        if last_rsi < 30:
            return 'buy'
        elif last_rsi > 70:
            return 'sell'
            
    except Exception as e:
        logger.error(f"Erro RSI Divergence: {e}")
    return None

def stochastic_strategy(df: pd.DataFrame) -> Optional[str]:
    """Stochastic Oscillator"""
    try:
        slowk, slowd = talib.STOCH(df['high'], df['low'], df['close'],
                                   fastk_period=14, slowk_period=3,
                                   slowk_matype=0, slowd_period=3, slowd_matype=0)
        
        last_k, last_d = slowk.iloc[-1], slowd.iloc[-1]
        prev_k, prev_d = slowk.iloc[-2], slowd.iloc[-2]
        
        # Oversold com crossover bullish
        if last_k < 20 and last_d < 20 and prev_k <= prev_d and last_k > last_d:
            return 'buy'
        
        # Overbought com crossover bearish
        if last_k > 80 and last_d > 80 and prev_k >= prev_d and last_k < last_d:
            return 'sell'
            
    except Exception as e:
        logger.error(f"Erro Stochastic: {e}")
    return None

def cci_strategy(df: pd.DataFrame) -> Optional[str]:
    """Commodity Channel Index"""
    try:
        cci = talib.CCI(df['high'], df['low'], df['close'], timeperiod=20)
        last_cci = cci.iloc[-1]
        prev_cci = cci.iloc[-2]
        
        # Saída de zona oversold
        if prev_cci < -100 and last_cci > -100:
            return 'buy'
        
        # Saída de zona overbought
        if prev_cci > 100 and last_cci < 100:
            return 'sell'
            
    except Exception as e:
        logger.error(f"Erro CCI: {e}")
    return None

def mfi_strategy(df: pd.DataFrame) -> Optional[str]:
    """Money Flow Index"""
    try:
        mfi = talib.MFI(df['high'], df['low'], df['close'], df['volume'], timeperiod=14)
        last_mfi = mfi.iloc[-1]
        
        if last_mfi < 20:
            return 'buy'
        elif last_mfi > 80:
            return 'sell'
            
    except Exception as e:
        logger.error(f"Erro MFI: {e}")
    return None

def williams_r_strategy(df: pd.DataFrame) -> Optional[str]:
    """Williams %R"""
    try:
        willr = talib.WILLR(df['high'], df['low'], df['close'], timeperiod=14)
        last_willr = willr.iloc[-1]
        
        if last_willr < -80:
            return 'buy'
        elif last_willr > -20:
            return 'sell'
            
    except Exception as e:
        logger.error(f"Erro Williams %R: {e}")
    return None

# =========================
# ESTRATÉGIAS DE REVERSÃO (3 estratégias)
# =========================
def bollinger_bands_strategy(df: pd.DataFrame) -> Optional[str]:
    """Bollinger Bands com squeezes"""
    try:
        upper, middle, lower = talib.BBANDS(df['close'], 
                                           timeperiod=20, 
                                           nbdevup=2, 
                                           nbdevdn=2, 
                                           matype=0)
        
        last_close = df['close'].iloc[-1]
        last_upper = upper.iloc[-1]
        last_lower = lower.iloc[-1]
        
        # Squeeze release (bandwidth)
        bandwidth = (upper - lower) / middle
        last_bandwidth = bandwidth.iloc[-1]
        prev_bandwidth = bandwidth.iloc[-2]
        
        # Reversão de banda inferior
        if last_close <= last_lower and last_bandwidth > prev_bandwidth:
            return 'buy'
        
        # Reversão de banda superior
        if last_close >= last_upper and last_bandwidth > prev_bandwidth:
            return 'sell'
            
    except Exception as e:
        logger.error(f"Erro Bollinger Bands: {e}")
    return None

def pivot_points_strategy(df: pd.DataFrame) -> Optional[str]:
    """Pivot Points clássicos"""
    try:
        # Calcula pivô do dia anterior
        prev_high = df['high'].iloc[-2]
        prev_low = df['low'].iloc[-2]
        prev_close = df['close'].iloc[-2]
        
        pivot = (prev_high + prev_low + prev_close) / 3
        r1 = 2 * pivot - prev_low
        s1 = 2 * pivot - prev_high
        r2 = pivot + (prev_high - prev_low)
        s2 = pivot - (prev_high - prev_low)
        
        current_price = df['close'].iloc[-1]
        
        # Suporte e resistência
        if current_price <= s1 and df['close'].iloc[-2] > s1:
            return 'buy'
        elif current_price >= r1 and df['close'].iloc[-2] < r1:
            return 'sell'
            
    except Exception as e:
        logger.error(f"Erro Pivot Points: {e}")
    return None

def support_resistance_strategy(df: pd.DataFrame, lookback: int = 50) -> Optional[str]:
    """Suporte e Resistência dinâmicos"""
    try:
        if len(df) < lookback:
            return None
        
        # Identifica níveis de S/R
        highs = df['high'].rolling(window=lookback).max()
        lows = df['low'].rolling(window=lookback).min()
        
        current_price = df['close'].iloc[-1]
        current_high = highs.iloc[-1]
        current_low = lows.iloc[-1]
        
        # Tolerância de 0.5%
        tolerance = current_price * 0.005
        
        # Teste de resistência
        if abs(current_price - current_high) <= tolerance:
            # Verifica rejeição
            if df['close'].iloc[-2] < current_high and df['high'].iloc[-1] >= current_high:
                return 'sell'
        
        # Teste de suporte
        if abs(current_price - current_low) <= tolerance:
            # Verifica rejeição
            if df['close'].iloc[-2] > current_low and df['low'].iloc[-1] <= current_low:
                return 'buy'
                
    except Exception as e:
        logger.error(f"Erro Support/Resistance: {e}")
    return None

# =========================
# ESTRATÉGIAS DE VOLUME (3 estratégias)
# =========================
def vwap_strategy(df: pd.DataFrame) -> Optional[str]:
    """Volume Weighted Average Price"""
    try:
        # Calcula VWAP
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        vwap = (typical_price * df['volume']).cumsum() / df['volume'].cumsum()
        
        last_close = df['close'].iloc[-1]
        last_vwap = vwap.iloc[-1]
        prev_close = df['close'].iloc[-2]
        prev_vwap = vwap.iloc[-2]
        
        # Preço cruzando acima do VWAP
        if prev_close <= prev_vwap and last_close > last_vwap:
            return 'buy'
        
        # Preço cruzando abaixo do VWAP
        if prev_close >= prev_vwap and last_close < last_vwap:
            return 'sell'
            
    except Exception as e:
        logger.error(f"Erro VWAP: {e}")
    return None

def obv_strategy(df: pd.DataFrame) -> Optional[str]:
    """On-Balance Volume"""
    try:
        obv = talib.OBV(df['close'], df['volume'])
        
        # Calcula OBV EMA
        obv_ema = talib.EMA(obv, timeperiod=20)
        
        last_obv = obv.iloc[-1]
        last_obv_ema = obv_ema.iloc[-1]
        prev_obv = obv.iloc[-2]
        prev_obv_ema = obv_ema.iloc[-2]
        
        # OBV cruzando acima da EMA
        if prev_obv <= prev_obv_ema and last_obv > last_obv_ema:
            return 'buy'
        
        # OBV cruzando abaixo da EMA
        if prev_obv >= prev_obv_ema and last_obv < last_obv_ema:
            return 'sell'
            
    except Exception as e:
        logger.error(f"Erro OBV: {e}")
    return None

def volume_profile_strategy(df: pd.DataFrame) -> Optional[str]:
    """Volume Profile simplificado"""
    try:
        # Volume acima da média
        volume_ma = df['volume'].rolling(20).mean()
        last_volume = df['volume'].iloc[-1]
        last_volume_ma = volume_ma.iloc[-1]
        
        # Price action com volume
        last_close = df['close'].iloc[-1]
        prev_close = df['close'].iloc[-2]
        last_high = df['high'].iloc[-1]
        last_low = df['low'].iloc[-1]
        
        # Volume spike com bullish candle
        if (last_volume > last_volume_ma * 1.5 and 
            last_close > prev_close and
            (last_close - last_low) > (last_high - last_close) * 2):  # Candle com baixa sombra longa
            return 'buy'
        
        # Volume spike com bearish candle
        if (last_volume > last_volume_ma * 1.5 and 
            last_close < prev_close and
            (last_high - last_close) > (last_close - last_low) * 2):  # Candle com alta sombra longa
            return 'sell'
            
    except Exception as e:
        logger.error(f"Erro Volume Profile: {e}")
    return None

# =========================
# ESTRATÉGIAS AVANÇADAS (3 estratégias)
# =========================
def fractals_strategy(df: pd.DataFrame) -> Optional[str]:
    """Fractals de Bill Williams"""
    try:
        # Fractal up (5 candles pattern)
        fractal_up = []
        for i in range(2, len(df)-2):
            if (df['high'].iloc[i] > df['high'].iloc[i-2] and
                df['high'].iloc[i] > df['high'].iloc[i-1] and
                df['high'].iloc[i] > df['high'].iloc[i+1] and
                df['high'].iloc[i] > df['high'].iloc[i+2]):
                fractal_up.append(i)
        
        # Fractal down (5 candles pattern)
        fractal_down = []
        for i in range(2, len(df)-2):
            if (df['low'].iloc[i] < df['low'].iloc[i-2] and
                df['low'].iloc[i] < df['low'].iloc[i-1] and
                df['low'].iloc[i] < df['low'].iloc[i+1] and
                df['low'].iloc[i] < df['low'].iloc[i+2]):
                fractal_down.append(i)
        
        if len(fractal_up) >= 2 and len(fractal_down) >= 1:
            # Último fractal up depois do último fractal down
            if max(fractal_up) > max(fractal_down):
                return 'buy'
        
        if len(fractal_down) >= 2 and len(fractal_up) >= 1:
            # Último fractal down depois do último fractal up
            if max(fractal_down) > max(fractal_up):
                return 'sell'
                
    except Exception as e:
        logger.error(f"Erro Fractals: {e}")
    return None

def market_structure_strategy(df: pd.DataFrame) -> Optional[str]:
    """Análise de estrutura de mercado (MSS)"""
    try:
        if len(df) < 30:
            return None
        
        # Identifica máximos e mínimos significativos
        highs = df['high'].values[-30:]
        lows = df['low'].values[-30:]
        
        # Higher Highs & Higher Lows (Uptrend)
        hh = all(highs[i] > highs[i-1] for i in range(-5, -1))
        hl = all(lows[i] > lows[i-1] for i in range(-5, -1))
        
        # Lower Highs & Lower Lows (Downtrend)
        lh = all(highs[i] < highs[i-1] for i in range(-5, -1))
        ll = all(lows[i] < lows[i-1] for i in range(-5, -1))
        
        # Mudança de estrutura
        if hh and hl:  # Uptrend confirmado
            # Break de último high
            if df['close'].iloc[-1] > max(highs[:-1]):
                return 'buy'
        
        elif lh and ll:  # Downtrend confirmado
            # Break de último low
            if df['close'].iloc[-1] < min(lows[:-1]):
                return 'sell'
                
    except Exception as e:
        logger.error(f"Erro Market Structure: {e}")
    return None

# =========================
# FILTROS E CONDIÇÕES
# =========================
def volume_filter(df: pd.DataFrame) -> bool:
    """Filtro de volume"""
    try:
        current_volume = df['volume'].iloc[-1]
        avg_volume = df['volume'].rolling(20).mean().iloc[-1]
        return current_volume > avg_volume * 1.2
    except:
        return False

def volatility_filter(df: pd.DataFrame, threshold: float = 0.002) -> bool:
    """Filtro de volatilidade"""
    try:
        atr = talib.ATR(df['high'], df['low'], df['close'], timeperiod=14).iloc[-1]
        current_price = df['close'].iloc[-1]
        return (atr / current_price) > threshold
    except:
        return False

def trend_filter(df: pd.DataFrame) -> str:
    """Identifica tendência geral"""
    try:
        ema50 = talib.EMA(df['close'], timeperiod=50).iloc[-1]
        ema200 = talib.EMA(df['close'], timeperiod=200).iloc[-1]
        current_price = df['close'].iloc[-1]
        
        if current_price > ema50 > ema200:
            return 'strong_bull'
        elif current_price > ema50 and ema50 > ema200:
            return 'bull'
        elif current_price < ema50 < ema200:
            return 'strong_bear'
        elif current_price < ema50 and ema50 < ema200:
            return 'bear'
        else:
            return 'neutral'
    except:
        return 'neutral'

# =========================
# GERAÇÃO DE SINAL
# =========================
def is_signal_duplicate(symbol: str, direction: str) -> bool:
    """Verifica se sinal é duplicado"""
    cache_key = f"{symbol}_{direction}"
    current_time = datetime.now()
    
    if cache_key in signal_cache:
        last_time = signal_cache[cache_key]
        if current_time - last_time < timedelta(minutes=5):
            return True
    
    signal_cache[cache_key] = current_time
    return False

def generate_signal(df: pd.DataFrame, symbol: str) -> Optional[str]:
    """Gera sinal combinando múltiplas estratégias"""
    try:
        if not volume_filter(df):
            return None
        
        # Executa estratégias ativas
        signals = {}
        strategy_functions = {
            'ema_crossover': ema_crossover_strategy,
            'macd_crossover': macd_crossover_strategy,
            'supertrend': lambda d: supertrend_strategy(d),
            'ichimoku': ichimoku_strategy,
            'adx_trend': adx_trend_strategy,
            'rsi_divergence': rsi_divergence_strategy,
            'stochastic': stochastic_strategy,
            'cci': cci_strategy,
            'mfi': mfi_strategy,
            'williams_r': williams_r_strategy,
            'bollinger_bands': bollinger_bands_strategy,
            'pivot_points': pivot_points_strategy,
            'support_resistance': lambda d: support_resistance_strategy(d),
            'vwap': vwap_strategy,
            'obv': obv_strategy,
            'volume_profile': volume_profile_strategy,
            'fractals': fractals_strategy,
            'market_structure': market_structure_strategy
        }
        
        for strategy_name, strategy_func in strategy_functions.items():
            if STRATEGIES[strategy_name]['active']:
                try:
                    signals[strategy_name] = strategy_func(df)
                except Exception as e:
                    logger.error(f"Erro na estratégia {strategy_name}: {e}")
                    signals[strategy_name] = None
        
        # Contagem ponderada por categoria
        category_scores = {
            'trend': {'buy': 0, 'sell': 0},
            'momentum': {'buy': 0, 'sell': 0},
            'reversal': {'buy': 0, 'sell': 0},
            'volume': {'buy': 0, 'sell': 0},
            'advanced': {'buy': 0, 'sell': 0}
        }
        
        for strategy_name, result in signals.items():
            if result:
                category = STRATEGIES[strategy_name]['category']
                weight = STRATEGIES[strategy_name]['weight']
                
                if result == 'buy':
                    category_scores[category]['buy'] += weight
                elif result == 'sell':
                    category_scores[category]['sell'] += weight
        
        # Calcula scores totais
        total_buy = sum(cat['buy'] for cat in category_scores.values())
        total_sell = sum(cat['sell'] for cat in category_scores.values())
        
        # Verifica consenso entre categorias
        categories_in_agreement = 0
        for category, scores in category_scores.items():
            if scores['buy'] > 0.5 and scores['buy'] > scores['sell']:
                categories_in_agreement += 1
            elif scores['sell'] > 0.5 and scores['sell'] > scores['buy']:
                categories_in_agreement += 1
        
        # Determina direção
        min_categories = 2  # Mínimo de 2 categorias concordando
        confidence_threshold = 2.5
        
        if categories_in_agreement >= min_categories:
            if total_buy >= confidence_threshold and not is_signal_duplicate(symbol, 'buy'):
                direction = 'COMPRA'
                emoji = '🚀'
                tp_mult = 1.003
                sl_mult = 0.998
                confidence_score = total_buy
            elif total_sell >= confidence_threshold and not is_signal_duplicate(symbol, 'sell'):
                direction = 'VENDA'
                emoji = '🔻'
                tp_mult = 0.997
                sl_mult = 1.002
                confidence_score = total_sell
            else:
                return None
            
            entry = df['close'].iloc[-1]
            tp = entry * tp_mult
            sl = entry * sl_mult
            
            # Identifica quais estratégias contribuíram
            contributing_strategies = []
            for strategy_name, result in signals.items():
                if result == direction.lower():
                    contributing_strategies.append(strategy_name.replace('_', ' ').title())
            
            # Formata mensagem
            formatted_entry = format_price(entry, symbol)
            formatted_tp = format_price(tp, symbol)
            formatted_sl = format_price(sl, symbol)
            
            signal_text = (
                f"{emoji} <b>SCALPING {direction} - MULTIESTRATÉGIA</b>\n"
                f"📊 Par: <code>{symbol}</code>\n"
                f"🏷️ Categoria: {get_pair_category(symbol)}\n"
                f"💰 Entrada: <b>{formatted_entry}</b>\n"
                f"🎯 TP: {formatted_tp} (+0.3%)\n"
                f"🛡️ SL: {formatted_sl} (-0.2%)\n"
                f"⏰ TF: 1m | 📈 Volume: Confirmado\n"
                f"🧮 Estratégias: {len(contributing_strategies)}/{len(signals)}\n"
                f"📊 Confiança: {confidence_score:.1f}/10.0\n"
                f"📋 Categorias concordantes: {categories_in_agreement}/5\n"
                f"🔄 Tendência: {trend_filter(df).replace('_', ' ').title()}\n"
                f"🕐 Hora: {datetime.now().strftime('%H:%M:%S')}\n"
            )
            
            # Adiciona estratégias contribuintes (máximo 5)
            if contributing_strategies:
                top_strategies = contributing_strategies[:5]
                signal_text += f"🏆 Top estratégias: {', '.join(top_strategies)}"
            
            # Armazena sinal
            signal_data = {
                'time': datetime.now(),
                'symbol': symbol,
                'direction': direction,
                'entry': entry,
                'tp': tp,
                'sl': sl,
                'confidence': confidence_score,
                'strategies_used': len(contributing_strategies),
                'categories_agreeing': categories_in_agreement,
                'trend': trend_filter(df),
                'text': signal_text
            }
            
            last_signals.append(signal_data)
            
            # Mantém apenas últimos 100 sinais
            if len(last_signals) > 100:
                last_signals.pop(0)
            
            return signal_text
            
    except Exception as e:
        logger.error(f"Erro ao gerar sinal para {symbol}: {e}")
    
    return None

# =========================
# SISTEMA DE MONITORAMENTO
# =========================
def check_signals():
    """Verifica sinais para todos os pares"""
    if signals_paused:
        return
    
    logger.info(f"Verificando {len(PAIRS)} pares...")
    
    signals_generated = 0
    for pair in PAIRS:
        try:
            df = get_binance_data(pair)
            if df is None or len(df) < 100:
                continue
            
            signal = generate_signal(df, pair)
            if signal:
                logger.info(f"✅ Sinal para {pair}")
                try:
                    bot.send_message(CHAT_ID, signal)
                    signals_generated += 1
                    time.sleep(0.3)  # Delay para não sobrecarregar API
                except Exception as e:
                    logger.error(f"Erro Telegram {pair}: {e}")
                    
        except Exception as e:
            logger.error(f"Erro ao processar {pair}: {e}")
    
    if signals_generated > 0:
        logger.info(f"Total de sinais gerados: {signals_generated}")

# =========================
# DASHBOARD FLASK EXPANDIDO
# =========================
app = Flask(__name__)

@app.route('/')
def dashboard():
    """Dashboard principal"""
    # Estatísticas
    total_signals = len(last_signals)
    buy_signals = len([s for s in last_signals if s['direction'] == 'COMPRA'])
    sell_signals = total_signals - buy_signals
    
    # Sinais recentes
    recent_signals = last_signals[-20:] if len(last_signals) > 20 else last_signals
    
    # Estratégias ativas
    active_strategies = sum(1 for s in STRATEGIES.values() if s['active'])
    
    # Categorias de pares
    pair_categories = {}
    for category, pairs in PAIR_CATEGORIES.items():
        pair_categories[category] = len(pairs)
    
    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Crypto Bot - Multi Strategy</title>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            :root {
                --primary: #2c3e50;
                --secondary: #3498db;
                --success: #27ae60;
                --danger: #e74c3c;
                --warning: #f39c12;
                --info: #17a2b8;
            }
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #1a2980, #26d0ce);
                color: #333;
                margin: 0;
                padding: 20px;
            }
            .container {
                max-width: 1600px;
                margin: 0 auto;
            }
            .header {
                background: rgba(255, 255, 255, 0.95);
                border-radius: 15px;
                padding: 25px;
                margin-bottom: 25px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.1);
                text-align: center;
            }
            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 15px;
                margin-bottom: 25px;
            }
            .stat-card {
                background: rgba(255, 255, 255, 0.95);
                border-radius: 10px;
                padding: 20px;
                text-align: center;
                box-shadow: 0 5px 15px rgba(0,0,0,0.08);
            }
            .stat-value {
                font-size: 2rem;
                font-weight: bold;
                margin: 10px 0;
            }
            .stat-label {
                color: #666;
                font-size: 0.9rem;
            }
            .card {
                background: rgba(255, 255, 255, 0.95);
                border-radius: 15px;
                padding: 25px;
                margin-bottom: 25px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.08);
            }
            .card h2 {
                color: var(--primary);
                border-bottom: 2px solid var(--secondary);
                padding-bottom: 10px;
                margin-top: 0;
            }
            .table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 15px;
            }
            .table th {
                background: #f8f9fa;
                padding: 12px;
                text-align: left;
                font-weight: 600;
                border-bottom: 2px solid #dee2e6;
            }
            .table td {
                padding: 12px;
                border-bottom: 1px solid #eee;
            }
            .buy-signal {
                border-left: 4px solid var(--success);
                background: rgba(39, 174, 96, 0.05);
            }
            .sell-signal {
                border-left: 4px solid var(--danger);
                background: rgba(231, 76, 60, 0.05);
            }
            .badge {
                display: inline-block;
                padding: 4px 12px;
                border-radius: 20px;
                font-size: 0.8rem;
                font-weight: 600;
            }
            .badge-buy {
                background: rgba(39, 174, 96, 0.1);
                color: var(--success);
            }
            .badge-sell {
                background: rgba(231, 76, 60, 0.1);
                color: var(--danger);
            }
            .badge-category {
                background: rgba(52, 152, 219, 0.1);
                color: var(--secondary);
            }
            .controls {
                display: flex;
                gap: 10px;
                margin: 20px 0;
            }
            .btn {
                padding: 12px 24px;
                border: none;
                border-radius: 8px;
                font-weight: 600;
                cursor: pointer;
                text-decoration: none;
                display: inline-flex;
                align-items: center;
                gap: 8px;
            }
            .btn-primary {
                background: var(--secondary);
                color: white;
            }
            .btn-success {
                background: var(--success);
                color: white;
            }
            .btn-danger {
                background: var(--danger);
                color: white;
            }
            .category-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 15px;
                margin-top: 15px;
            }
            .category-item {
                background: #f8f9fa;
                padding: 15px;
                border-radius: 8px;
                border-left: 4px solid var(--secondary);
            }
            .progress-bar {
                height: 8px;
                background: #e9ecef;
                border-radius: 4px;
                margin: 10px 0;
                overflow: hidden;
            }
            .progress-fill {
                height: 100%;
                border-radius: 4px;
            }
            .progress-buy {
                background: var(--success);
            }
            .progress-sell {
                background: var(--danger);
            }
        </style>
    </head>
    <body>
        <div class="container">
            <!-- Header -->
            <div class="header">
                <h1><i class="fas fa-robot"></i> Crypto Bot - Multi Strategy</h1>
                <p>Monitorando {{ pairs_count }} pares com {{ strategies_count }} estratégias</p>
                <div class="controls">
                    {% if not paused %}
                    <a href="/pause" class="btn btn-danger">
                        <i class="fas fa-pause"></i> Pausar Bot
                    </a>
                    {% else %}
                    <a href="/resume" class="btn btn-success">
                        <i class="fas fa-play"></i> Retomar Bot
                    </a>
                    {% endif %}
                    <a href="/strategies" class="btn btn-primary">
                        <i class="fas fa-cogs"></i> Estratégias
                    </a>
                    <a href="/pairs" class="btn btn-primary">
                        <i class="fas fa-coins"></i> Pares
                    </a>
                </div>
            </div>
            
            <!-- Stats Grid -->
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-label">Pares Ativos</div>
                    <div class="stat-value">{{ pairs_count }}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Estratégias</div>
                    <div class="stat-value">{{ strategies_count }}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Sinais Totais</div>
                    <div class="stat-value">{{ total_signals }}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Buy/Sell Ratio</div>
                    <div class="stat-value">{{ buy_signals }}/{{ sell_signals }}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Uptime</div>
                    <div class="stat-value">{{ uptime }}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Status</div>
                    <div class="stat-value" style="color: {{ 'var(--success)' if not paused else 'var(--danger)' }}">
                        {{ 'ATIVO' if not paused else 'PAUSADO' }}
                    </div>
                </div>
            </div>
            
            <!-- Recent Signals -->
            <div class="card">
                <h2><i class="fas fa-history"></i> Sinais Recentes</h2>
                {% if recent_signals %}
                <table class="table">
                    <thead>
                        <tr>
                            <th>Hora</th>
                            <th>Par</th>
                            <th>Direção</th>
                            <th>Entrada</th>
                            <th>Confiança</th>
                            <th>Estratégias</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for signal in recent_signals|reverse %}
                        <tr class="{{ 'buy-signal' if signal.direction == 'COMPRA' else 'sell-signal' }}">
                            <td>{{ signal.time.strftime('%H:%M:%S') }}</td>
                            <td><strong>{{ signal.symbol }}</strong></td>
                            <td>
                                <span class="badge {{ 'badge-buy' if signal.direction == 'COMPRA' else 'badge-sell' }}">
                                    {{ signal.direction }}
                                </span>
                            </td>
                            <td>${{ format_price(signal.entry, signal.symbol) }}</td>
                            <td>
                                <div class="progress-bar">
                                    <div class="progress-fill {{ 'progress-buy' if signal.direction == 'COMPRA' else 'progress-sell' }}" 
                                         style="width: {{ (signal.confidence/10)*100 }}%">
                                    </div>
                                </div>
                                {{ signal.confidence|round(1) }}/10
                            </td>
                            <td>{{ signal.strategies_used }} estratégias</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
                {% else %}
                <p style="text-align: center; color: #666; padding: 40px;">
                    <i class="fas fa-inbox" style="font-size: 3rem; color: #ddd;"></i><br>
                    Nenhum sinal gerado ainda
                </p>
                {% endif %}
            </div>
            
            <!-- Categories -->
            <div class="card">
                <h2><i class="fas fa-layer-group"></i> Categorias de Pares</h2>
                <div class="category-grid">
                    {% for category, count in pair_categories.items() %}
                    <div class="category-item">
                        <h3 style="margin: 0 0 10px 0; color: var(--primary);">
                            {{ category.replace('_', ' ').title() }}
                        </h3>
                        <p style="margin: 0; color: #666;">
                            {{ count }} pares
                        </p>
                        <div style="margin-top: 10px; font-size: 0.9rem;">
                            {% for pair in PAIR_CATEGORIES[category][:5] %}
                            <span class="badge badge-category" style="margin: 2px;">{{ pair }}</span>
                            {% endfor %}
                            {% if count > 5 %}
                            <span style="color: #999;">+{{ count-5 }} mais</span>
                            {% endif %}
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
            
            <!-- Footer -->
            <div style="text-align: center; color: white; margin-top: 30px; padding: 20px;">
                <p>
                    <i class="fas fa-sync-alt"></i> Atualização automática em 60s |
                    <i class="fas fa-server"></i> Render.com |
                    <i class="fas fa-code"></i> Python 3.10
                </p>
                <p style="font-size: 0.9rem; opacity: 0.8;">
                    Última atualização: {{ current_time }}
                </p>
            </div>
        </div>
        
        <script>
            // Auto-refresh
            setTimeout(() => location.reload(), 60000);
            
            // Confirmações
            document.querySelectorAll('.btn-danger, .btn-success').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    if (!confirm('Tem certeza?')) e.preventDefault();
                });
            });
        </script>
    </body>
    </html>
    """
    
    return render_template_string(
        html_template,
        pairs_count=len(PAIRS),
        strategies_count=active_strategies,
        total_signals=total_signals,
        buy_signals=buy_signals,
        sell_signals=sell_signals,
        recent_signals=recent_signals,
        pair_categories=pair_categories,
        paused=signals_paused,
        uptime=get_uptime(),
        current_time=datetime.now().strftime('%H:%M:%S'),
        format_price=format_price
    )

@app.route('/strategies')
def strategies_page():
    """Página de configuração das estratégias"""
    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Configuração de Estratégias</title>
        <style>
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #1a2980, #26d0ce);
                color: #333;
                margin: 0;
                padding: 20px;
            }
            .container {
                max-width: 1200px;
                margin: 0 auto;
                background: rgba(255, 255, 255, 0.95);
                border-radius: 15px;
                padding: 30px;
            }
            .back-btn {
                display: inline-block;
                margin-bottom: 20px;
                padding: 10px 20px;
                background: #3498db;
                color: white;
                text-decoration: none;
                border-radius: 8px;
            }
            .strategy-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
                gap: 20px;
                margin-top: 20px;
            }
            .strategy-card {
                background: white;
                border-radius: 10px;
                padding: 20px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.1);
                border-left: 4px solid #3498db;
            }
            .category-badge {
                display: inline-block;
                padding: 4px 12px;
                border-radius: 20px;
                font-size: 0.8rem;
                margin: 5px 0;
            }
            .trend { background: #e3f2fd; color: #1976d2; }
            .momentum { background: #f3e5f5; color: #7b1fa2; }
            .reversal { background: #e8f5e9; color: #388e3c; }
            .volume { background: #fff3e0; color: #f57c00; }
            .advanced { background: #fce4ec; color: #c2185b; }
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-btn">← Voltar</a>
            <h1>Configuração de Estratégias</h1>
            <p>Total: {{ total_strategies }} | Ativas: {{ active_strategies }}</p>
            
            <form action="/update_strategies" method="post">
                <div class="strategy-grid">
                    {% for name, config in strategies.items() %}
                    <div class="strategy-card">
                        <h3>{{ name.replace('_', ' ').title() }}</h3>
                        <span class="category-badge {{ config.category }}">
                            {{ config.category }}
                        </span>
                        <p>Peso: {{ config.weight }}</p>
                        <label>
                            <input type="checkbox" name="{{ name }}" {{ 'checked' if config.active }}>
                            Ativar estratégia
                        </label>
                    </div>
                    {% endfor %}
                </div>
                
                <div style="margin-top: 30px; text-align: center;">
                    <button type="submit" style="padding: 12px 30px; background: #27ae60; color: white; border: none; border-radius: 8px; font-size: 1.1rem;">
                        Salvar Configurações
                    </button>
                </div>
            </form>
        </div>
    </body>
    </html>
    '''
    
    active_strategies = sum(1 for s in STRATEGIES.values() if s['active'])
    
    return render_template_string(
        html,
        strategies=STRATEGIES,
        total_strategies=len(STRATEGIES),
        active_strategies=active_strategies
    )

# =========================
# FUNÇÕES PRINCIPAIS
# =========================
def run_flask():
    """Executa servidor Flask"""
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

def run_signal_checker():
    """Executa verificação periódica de sinais"""
    logger.info("Iniciando verificador de sinais...")
    
    # Verifica a cada 1 minuto
    schedule.every(1).minutes.do(check_signals)
    
    while True:
        schedule.run_pending()
        time.sleep(1)

def main():
    """Função principal"""
    logger.info("=" * 60)
    logger.info("CRYPTO BOT - MULTI STRATEGY")
    logger.info("=" * 60)
    logger.info(f"Pares: {len(PAIRS)}")
    logger.info(f"Estratégias: {sum(1 for s in STRATEGIES.values() if s['active'])}/{len(STRATEGIES)}")
    logger.info(f"Dashboard: http://localhost:10000")
    logger.info("=" * 60)
    
    # Envia mensagem de início
    try:
        startup_msg = (
            f"🤖 <b>CRYPTO BOT INICIADO</b>\n\n"
            f"📊 <b>Configuração:</b>\n"
            f"• Pares: {len(PAIRS)}\n"
            f"• Estratégias: {sum(1 for s in STRATEGIES.values() if s['active'])}\n"
            f"• Categorias: {len(PAIR_CATEGORIES)}\n"
            f"• Intervalo: 1 minuto\n\n"
            f"✅ Sistema operacional!"
        )
        bot.send_message(CHAT_ID, startup_msg)
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem inicial: {e}")
    
    # Inicia threads
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    signal_thread = threading.Thread(target=run_signal_checker, daemon=True)
    
    flask_thread.start()
    signal_thread.start()
    
    # Mantém thread principal ativa
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Bot encerrado pelo usuário")

if __name__ == "__main__":
    # Instalação necessária: pip install TA-Lib
    # Para Linux: sudo apt-get install libta-lib-dev
    # Para Windows: baixe o .whl apropriado
    main()
