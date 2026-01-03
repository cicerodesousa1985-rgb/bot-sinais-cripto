import telebot
import requests
import pandas as pd
import time
import schedule
import threading
from flask import Flask, render_template_string, request, jsonify
import os
from datetime import datetime, timedelta
import logging
from typing import Optional, List, Dict, Tuple
import json
import numpy as np
from sklearn.ensemble import RandomForestClassifier, IsolationForest
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import DBSCAN
import yfinance as yf  # Para dados adicionais
import warnings
warnings.filterwarnings('ignore')

# =========================
# CONFIGURAÇÃO DE LOG
# =========================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_scalping_ai.log'),
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

# Configuração de pares
PAIRS = [
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT',
    'ADAUSDT', 'XRPUSDT', 'DOGEUSDT', 'LINKUSDT', 'AVAXUSDT'
]

# Modelos de IA
ml_models = {
    'random_forest': None,
    'anomaly_detector': None,
    'scaler': StandardScaler(),
    'market_sentiment': 'NEUTRAL'
}

# Configurações de estratégia com IA
STRATEGIES = {
    'ema_vwap': {'weight': 1.0, 'active': True},
    'rsi_scalping': {'weight': 0.8, 'active': True},
    'macd': {'weight': 0.9, 'active': True},
    'ai_predictor': {'weight': 1.2, 'active': True},
    'sentiment_analysis': {'weight': 0.7, 'active': True}
}

# =========================
# IA: COLETA DE DADOS PARA TREINAMENTO
# =========================
def collect_training_data(symbol: str, days: int = 30) -> pd.DataFrame:
    """Coleta dados históricos para treinamento"""
    try:
        # Usa yfinance para dados históricos
        ticker = symbol.replace('USDT', '-USD') if symbol.endswith('USDT') else symbol
        data = yf.download(ticker, period=f'{days}d', interval='1m')
        
        if data.empty:
            logger.warning(f"Sem dados para treinamento de {symbol}")
            return pd.DataFrame()
        
        # Calcula features
        data['returns'] = data['Close'].pct_change()
        data['volume_change'] = data['Volume'].pct_change()
        data['high_low_ratio'] = data['High'] / data['Low']
        data['close_open_ratio'] = data['Close'] / data['Open']
        
        # RSI
        delta = data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        data['RSI'] = 100 - (100 / (1 + rs))
        
        # MACD
        exp1 = data['Close'].ewm(span=12, adjust=False).mean()
        exp2 = data['Close'].ewm(span=26, adjust=False).mean()
        data['MACD'] = exp1 - exp2
        data['MACD_Signal'] = data['MACD'].ewm(span=9, adjust=False).mean()
        
        # Labels (1 se próximo candle for positivo, 0 caso contrário)
        data['target'] = (data['Close'].shift(-1) > data['Close']).astype(int)
        
        return data.dropna()
        
    except Exception as e:
        logger.error(f"Erro ao coletar dados de treinamento: {e}")
        return pd.DataFrame()

def train_ai_model(symbol: str):
    """Treina modelo de IA para previsão"""
    try:
        logger.info(f"Treinando modelo IA para {symbol}...")
        
        # Coleta dados
        data = collect_training_data(symbol)
        if data.empty or len(data) < 100:
            logger.warning(f"Dados insuficientes para treinar {symbol}")
            return
        
        # Features para treinamento
        features = [
            'returns', 'volume_change', 'high_low_ratio', 
            'close_open_ratio', 'RSI', 'MACD', 'MACD_Signal',
            'Volume'
        ]
        
        X = data[features].values
        y = data['target'].values
        
        if len(np.unique(y)) < 2:
            logger.warning(f"Classes insuficientes para {symbol}")
            return
        
        # Normaliza os dados
        X_scaled = ml_models['scaler'].fit_transform(X)
        
        # Treina Random Forest
        rf_model = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            random_state=42,
            n_jobs=-1
        )
        rf_model.fit(X_scaled, y)
        
        # Treina detector de anomalias
        anomaly_model = IsolationForest(
            contamination=0.1,
            random_state=42
        )
        anomaly_model.fit(X_scaled)
        
        ml_models['random_forest'] = rf_model
        ml_models['anomaly_detector'] = anomaly_model
        
        accuracy = rf_model.score(X_scaled, y)
        logger.info(f"Modelo IA treinado para {symbol} - Acurácia: {accuracy:.2%}")
        
        # Salva modelo treinado
        import joblib
        joblib.dump({
            'rf_model': rf_model,
            'anomaly_model': anomaly_model,
            'scaler': ml_models['scaler'],
            'features': features,
            'accuracy': accuracy,
            'trained_at': datetime.now()
        }, f'model_{symbol}.pkl')
        
    except Exception as e:
        logger.error(f"Erro ao treinar modelo IA: {e}")

# =========================
# IA: ANÁLISE DE SENTIMENTO DE MERCADO
# =========================
def analyze_market_sentiment() -> str:
    """Analisa sentimento do mercado usando múltiplas fontes"""
    try:
        sentiment_scores = []
        
        # 1. Análise de Fear & Greed Index (simulado)
        fear_greed = np.random.uniform(20, 80)  # Simulado - na prática usar API
        sentiment_scores.append(fear_greed)
        
        # 2. Análise de volume total do mercado
        total_volume = 0
        for pair in PAIRS[:3]:  # Apenas principais pares
            try:
                df = get_binance_data(pair, interval='5m', limit=10)
                if df is not None:
                    total_volume += df['volume'].iloc[-1]
            except:
                pass
        
        # Normaliza volume
        if total_volume > 0:
            volume_score = min(100, total_volume / 1000000)  # Ajuste conforme necessário
            sentiment_scores.append(volume_score)
        
        # 3. Análise de tendência de mercado
        trend_score = analyze_market_trend()
        sentiment_scores.append(trend_score)
        
        # Calcula sentimento médio
        if sentiment_scores:
            avg_score = np.mean(sentiment_scores)
            
            if avg_score >= 70:
                sentiment = "BULLISH"
            elif avg_score >= 40:
                sentiment = "NEUTRAL"
            else:
                sentiment = "BEARISH"
            
            ml_models['market_sentiment'] = sentiment
            ml_models['sentiment_score'] = avg_score
            
            return sentiment
        
    except Exception as e:
        logger.error(f"Erro na análise de sentimento: {e}")
    
    return "NEUTRAL"

def analyze_market_trend() -> float:
    """Analisa tendência geral do mercado"""
    try:
        trend_scores = []
        
        for pair in PAIRS[:5]:  # Análise dos 5 principais pares
            df = get_binance_data(pair, interval='15m', limit=20)
            if df is not None and len(df) > 10:
                # Calcula média móvel simples
                sma_short = df['close'].rolling(window=5).mean().iloc[-1]
                sma_long = df['close'].rolling(window=20).mean().iloc[-1]
                
                if sma_short > sma_long:
                    trend_scores.append(70)  # Tendência de alta
                elif sma_short < sma_long:
                    trend_scores.append(30)  # Tendência de baixa
                else:
                    trend_scores.append(50)  # Lateral
        
        return np.mean(trend_scores) if trend_scores else 50.0
    except:
        return 50.0

# =========================
# IA: PREDIÇÃO COM MACHINE LEARNING
# =========================
def ai_prediction_strategy(df: pd.DataFrame, symbol: str) -> Optional[str]:
    """Usa IA para prever direção do próximo candle"""
    if ml_models['random_forest'] is None:
        # Tenta carregar modelo salvo
        try:
            import joblib
            model_data = joblib.load(f'model_{symbol}.pkl')
            ml_models['random_forest'] = model_data['rf_model']
            ml_models['anomaly_detector'] = model_data['anomaly_model']
            ml_models['scaler'] = model_data['scaler']
        except:
            # Treina modelo se não existir
            train_ai_model(symbol)
            return None
    
    try:
        # Prepara features atuais
        current_features = pd.DataFrame({
            'returns': [df['close'].pct_change().iloc[-1]],
            'volume_change': [df['volume'].pct_change().iloc[-1]],
            'high_low_ratio': [df['high'].iloc[-1] / df['low'].iloc[-1]],
            'close_open_ratio': [df['close'].iloc[-1] / df['open'].iloc[-1]],
            'RSI': [calculate_rsi(df).iloc[-1]],
            'MACD': [calculate_macd(df)[0].iloc[-1]],
            'MACD_Signal': [calculate_macd(df)[1].iloc[-1]],
            'Volume': [df['volume'].iloc[-1]]
        })
        
        # Verifica por valores NaN
        if current_features.isnull().any().any():
            return None
        
        # Normaliza features
        features_scaled = ml_models['scaler'].transform(current_features)
        
        # Faz predição
        prediction = ml_models['random_forest'].predict(features_scaled)[0]
        probability = ml_models['random_forest'].predict_proba(features_scaled)[0]
        
        # Detecção de anomalia
        anomaly_score = ml_models['anomaly_detector'].score_samples(features_scaled)[0]
        
        # Confiança baseada na probabilidade e anomalia
        confidence = probability[prediction] * (1 - abs(anomaly_score))
        
        if prediction == 1 and confidence > 0.6:  # Confiança mínima de 60%
            return 'buy'
        elif prediction == 0 and confidence > 0.6:
            return 'sell'
        
    except Exception as e:
        logger.error(f"Erro na predição IA para {symbol}: {e}")
    
    return None

# =========================
# IA: ANÁLISE DE PADRÕES GRÁFICOS
# =========================
def detect_chart_patterns(df: pd.DataFrame) -> Dict:
    """Detecta padrões gráficos comuns"""
    patterns = {
        'double_top': False,
        'double_bottom': False,
        'head_shoulders': False,
        'triangle': False,
        'flag': False
    }
    
    try:
        prices = df['close'].values[-50:]  # Últimos 50 preços
        
        if len(prices) < 20:
            return patterns
        
        # Detecta Double Top
        if detect_double_top(prices):
            patterns['double_top'] = True
        
        # Detecta Double Bottom
        if detect_double_bottom(prices):
            patterns['double_bottom'] = True
        
        # Detecta Head and Shoulders (simplificado)
        if detect_head_shoulders(prices):
            patterns['head_shoulders'] = True
        
        # Detecta Triângulo
        if detect_triangle_pattern(df):
            patterns['triangle'] = True
        
    except Exception as e:
        logger.error(f"Erro na detecção de padrões: {e}")
    
    return patterns

def detect_double_top(prices: np.array) -> bool:
    """Detecta padrão Double Top"""
    if len(prices) < 20:
        return False
    
    # Encontra picos
    from scipy.signal import find_peaks
    peaks, _ = find_peaks(prices, distance=10)
    
    if len(peaks) >= 2:
        # Dois picos próximos em nível similar
        peak1 = prices[peaks[-2]]
        peak2 = prices[peaks[-1]]
        
        if abs(peak1 - peak2) / peak1 < 0.02:  # Diferença menor que 2%
            # Verifica se há valle entre os picos
            trough = np.min(prices[peaks[-2]:peaks[-1]])
            if trough < peak1 * 0.95:  # Queda de pelo menos 5%
                return True
    
    return False

def detect_double_bottom(prices: np.array) -> bool:
    """Detecta padrão Double Bottom"""
    if len(prices) < 20:
        return False
    
    # Encontra vales
    from scipy.signal import find_peaks
    valleys, _ = find_peaks(-prices, distance=10)
    
    if len(valleys) >= 2:
        # Dois vales próximos em nível similar
        valley1 = prices[valleys[-2]]
        valley2 = prices[valleys[-1]]
        
        if abs(valley1 - valley2) / valley1 < 0.02:  # Diferença menor que 2%
            # Verifica se há pico entre os vales
            peak = np.max(prices[valleys[-2]:valleys[-1]])
            if peak > valley1 * 1.05:  # Alta de pelo menos 5%
                return True
    
    return False

def detect_head_shoulders(prices: np.array) -> bool:
    """Detecta padrão Head and Shoulders (simplificado)"""
    if len(prices) < 30:
        return False
    
    # Encontra picos
    from scipy.signal import find_peaks
    peaks, _ = find_peaks(prices, distance=8)
    
    if len(peaks) >= 3:
        # Verifica padrão: pico do meio mais alto
        if peaks[1] > peaks[0] and peaks[1] > peaks[2]:
            # Picos laterais em níveis similares
            if abs(prices[peaks[0]] - prices[peaks[2]]) / prices[peaks[0]] < 0.03:
                return True
    
    return False

def detect_triangle_pattern(df: pd.DataFrame) -> bool:
    """Detecta padrão de triângulo (simetria)"""
    if len(df) < 30:
        return False
    
    highs = df['high'].values[-30:]
    lows = df['low'].values[-30:]
    
    # Calcula linhas de tendência
    high_slope = np.polyfit(range(len(highs)), highs, 1)[0]
    low_slope = np.polyfit(range(len(lows)), lows, 1)[0]
    
    # Triângulo simétrico: altas descendo e baixas subindo
    if high_slope < -0.001 and low_slope > 0.001:
        return True
    
    return False

# =========================
# IA: SISTEMA DE RECOMENDAÇÃO INTELIGENTE
# =========================
def intelligent_recommendation(df: pd.DataFrame, symbol: str) -> Dict:
    """Gera recomendação inteligente combinando múltiplas técnicas de IA"""
    recommendation = {
        'action': 'HOLD',
        'confidence': 0.0,
        'reasons': [],
        'risk_level': 'MEDIUM',
        'expected_return': 0.0,
        'stop_loss': 0.0,
        'take_profit': 0.0
    }
    
    try:
        scores = {
            'buy': 0.0,
            'sell': 0.0,
            'hold': 0.0
        }
        
        reasons = []
        
        # 1. Predição de Machine Learning
        if STRATEGIES['ai_predictor']['active']:
            ai_pred = ai_prediction_strategy(df, symbol)
            if ai_pred == 'buy':
                scores['buy'] += 1.2
                reasons.append("📈 IA prevê alta")
            elif ai_pred == 'sell':
                scores['sell'] += 1.2
                reasons.append("📉 IA prevê baixa")
        
        # 2. Análise de Sentimento
        if STRATEGIES['sentiment_analysis']['active']:
            sentiment = ml_models['market_sentiment']
            if sentiment == "BULLISH":
                scores['buy'] += 0.8
                reasons.append("🐂 Sentimento bullish")
            elif sentiment == "BEARISH":
                scores['sell'] += 0.8
                reasons.append("🐻 Sentimento bearish")
        
        # 3. Padrões Gráficos
        patterns = detect_chart_patterns(df)
        if patterns['double_bottom']:
            scores['buy'] += 0.6
            reasons.append("👆 Double Bottom detectado")
        if patterns['double_top']:
            scores['sell'] += 0.6
            reasons.append("👇 Double Top detectado")
        if patterns['head_shoulders']:
            scores['sell'] += 0.7
            reasons.append("👤 Head & Shoulders detectado")
        
        # 4. Análise Técnica Tradicional (já existente)
        rsi_val = calculate_rsi(df).iloc[-1]
        if rsi_val < 35:
            scores['buy'] += 0.5
            reasons.append("📊 RSI sobrevendido")
        elif rsi_val > 65:
            scores['sell'] += 0.5
            reasons.append("📊 RSI sobrecomprado")
        
        # 5. Volume Anormal (detecção de anomalia)
        try:
            if ml_models['anomaly_detector'] is not None:
                current_features = prepare_features_for_anomaly(df)
                anomaly_score = ml_models['anomaly_detector'].score_samples([current_features])[0]
                if anomaly_score < -0.5:  # Anomalia significativa
                    scores['hold'] += 1.0
                    reasons.append("⚠️ Volume/Preço anômalo detectado")
        except:
            pass
        
        # Determina ação recomendada
        max_score = max(scores.values())
        max_action = max(scores, key=scores.get)
        
        if max_score > 1.5:  # Limiar de confiança
            recommendation['action'] = max_action.upper()
            recommendation['confidence'] = min(max_score / 3.0, 1.0)  # Normaliza para 0-1
            recommendation['reasons'] = reasons
            
            # Calcula níveis de risco e retorno
            current_price = df['close'].iloc[-1]
            if max_action == 'buy':
                recommendation['expected_return'] = 0.003  # 0.3%
                recommendation['take_profit'] = current_price * 1.003
                recommendation['stop_loss'] = current_price * 0.998
                recommendation['risk_level'] = 'LOW' if recommendation['confidence'] > 0.7 else 'MEDIUM'
            elif max_action == 'sell':
                recommendation['expected_return'] = 0.003  # 0.3%
                recommendation['take_profit'] = current_price * 0.997
                recommendation['stop_loss'] = current_price * 1.002
                recommendation['risk_level'] = 'LOW' if recommendation['confidence'] > 0.7 else 'MEDIUM'
            else:
                recommendation['risk_level'] = 'LOW'
        
    except Exception as e:
        logger.error(f"Erro na recomendação inteligente: {e}")
    
    return recommendation

def prepare_features_for_anomaly(df: pd.DataFrame) -> List[float]:
    """Prepara features para detecção de anomalia"""
    features = []
    
    # Features de preço
    features.append(df['close'].pct_change().iloc[-1])
    features.append(df['high'].iloc[-1] / df['low'].iloc[-1])
    
    # Features de volume
    features.append(df['volume'].pct_change().iloc[-1])
    features.append(df['volume'].iloc[-1] / df['volume'].rolling(20).mean().iloc[-1])
    
    # Features técnicas
    features.append(calculate_rsi(df).iloc[-1] / 100)  # Normalizado 0-1
    macd_line, _ = calculate_macd(df)
    features.append(macd_line.iloc[-1] / df['close'].iloc[-1])  # Normalizado
    
    return features

# =========================
# ATUALIZAÇÃO DAS ESTRATÉGIAS PARA INCLUIR IA
# =========================
def ai_enhanced_strategy(df: pd.DataFrame, symbol: str) -> Optional[str]:
    """Estratégia aprimorada com IA"""
    recommendation = intelligent_recommendation(df, symbol)
    
    if recommendation['action'] in ['BUY', 'SELL'] and recommendation['confidence'] > 0.6:
        return recommendation['action'].lower()
    
    return None

# =========================
# ATUALIZAÇÃO DA GERAÇÃO DE SINAL
# =========================
def generate_signal(df: pd.DataFrame, symbol: str) -> Optional[str]:
    """Gera sinal aprimorado com IA"""
    try:
        if not volume_filter(df):
            return None
        
        # Executa estratégias ativas incluindo IA
        signals = {}
        if STRATEGIES['ema_vwap']['active']:
            signals['ema_vwap'] = ema_vwap_strategy(df)
        if STRATEGIES['rsi_scalping']['active']:
            signals['rsi_scalping'] = rsi_scalping_strategy(df)
        if STRATEGIES['macd']['active']:
            signals['macd'] = macd_strategy(df)
        if STRATEGIES['ai_predictor']['active']:
            signals['ai_predictor'] = ai_enhanced_strategy(df, symbol)
        
        # Análise de sentimento (contribui para decisão)
        sentiment_bonus = 0
        if STRATEGIES['sentiment_analysis']['active']:
            sentiment = analyze_market_sentiment()
            if sentiment == "BULLISH":
                sentiment_bonus = 0.3
            elif sentiment == "BEARISH":
                sentiment_bonus = -0.3
        
        # Contagem ponderada com IA
        buy_score = 0
        sell_score = 0
        
        for strategy, result in signals.items():
            if result:
                weight = STRATEGIES[strategy]['weight']
                if result == 'buy':
                    buy_score += weight
                elif result == 'sell':
                    sell_score += weight
        
        # Adiciona bônus de sentimento
        buy_score += max(sentiment_bonus, 0)
        sell_score += max(-sentiment_bonus, 0)
        
        # Determina direção com IA
        threshold = 1.8  # Limiar mais alto para maior confiança
        
        if buy_score >= threshold or sell_score >= threshold:
            if buy_score > sell_score and not is_signal_duplicate(symbol, 'buy'):
                direction = 'COMPRA'
                emoji = '🚀'
                tp_mult = 1.003
                sl_mult = 0.998
                confidence_score = buy_score
            elif sell_score > buy_score and not is_signal_duplicate(symbol, 'sell'):
                direction = 'VENDA'
                emoji = '🔻'
                tp_mult = 0.997
                sl_mult = 1.002
                confidence_score = sell_score
            else:
                return None
            
            entry = df['close'].iloc[-1]
            tp = entry * tp_mult
            sl = entry * sl_mult
            
            # Obtém recomendação IA para informações adicionais
            recommendation = intelligent_recommendation(df, symbol)
            
            # Formata mensagem aprimorada
            formatted_entry = format_price(entry, symbol)
            formatted_tp = format_price(tp, symbol)
            formatted_sl = format_price(sl, symbol)
            
            # Emojis baseados na confiança
            confidence_emoji = '🎯' if confidence_score >= 2.5 else '⚡' if confidence_score >= 2.0 else '📈'
            
            # Mensagem rica com IA
            signal_text = (
                f"{emoji} <b>🤖 SCALPING {direction} COM IA</b>\n"
                f"📊 Par: <code>{symbol}</code>\n"
                f"💰 Entrada: <b>{formatted_entry}</b>\n"
                f"🎯 TP: {formatted_tp} (+0.3%)\n"
                f"🛡️ SL: {formatted_sl} (-0.2%)\n"
                f"⏰ TF: 1m | 📈 Volume: Ativo\n"
                f"🧠 IA Confiança: {confidence_score:.1f}/4.0 {confidence_emoji}\n"
                f"📋 Risco: {recommendation['risk_level']}\n"
                f"🎲 Probabilidade: {recommendation['confidence']:.0%}\n"
                f"🕐 Hora: {datetime.now().strftime('%H:%M:%S')}\n"
            )
            
            # Adiciona razões se disponíveis
            if recommendation['reasons']:
                signal_text += f"📝 Razões: {', '.join(recommendation['reasons'][:3])}\n"
            
            # Adiciona sentimento do mercado
            sentiment = ml_models.get('market_sentiment', 'NEUTRAL')
            sentiment_emoji = '🐂' if sentiment == 'BULLISH' else '🐻' if sentiment == 'BEARISH' else '➖'
            signal_text += f"🌡️ Sentimento: {sentiment} {sentiment_emoji}"
            
            # Armazena sinal com metadados de IA
            signal_data = {
                'time': datetime.now(),
                'symbol': symbol,
                'direction': direction,
                'entry': entry,
                'tp': tp,
                'sl': sl,
                'confidence': confidence_score,
                'ai_confidence': recommendation['confidence'],
                'risk_level': recommendation['risk_level'],
                'sentiment': sentiment,
                'reasons': recommendation['reasons'],
                'text': signal_text
            }
            
            last_signals.append(signal_data)
            
            # Mantém apenas últimos 50 sinais
            if len(last_signals) > 50:
                last_signals.pop(0)
            
            return signal_text
            
    except Exception as e:
        logger.error(f"Erro ao gerar sinal IA para {symbol}: {e}")
    
    return None

# =========================
# NOVOS COMANDOS TELEGRAM PARA IA
# =========================
@bot.message_handler(commands=['ai_train'])
def train_ai_command(message):
    """Comando para treinar modelos de IA"""
    bot.reply_to(message, "🧠 <b>Iniciando treinamento de IA...</b>")
    
    # Treina para cada par
    trained_count = 0
    for pair in PAIRS[:3]:  # Treina apenas para os 3 principais
        try:
            train_ai_model(pair)
            trained_count += 1
        except Exception as e:
            logger.error(f"Erro ao treinar {pair}: {e}")
    
    bot.reply_to(message, f"✅ <b>Treinamento concluído</b>\nModelos treinados: {trained_count}")

@bot.message_handler(commands=['ai_status'])
def ai_status_command(message):
    """Status dos modelos de IA"""
    rf_status = "✅" if ml_models['random_forest'] is not None else "❌"
    anomaly_status = "✅" if ml_models['anomaly_detector'] is not None else "❌"
    sentiment = ml_models.get('market_sentiment', 'Desconhecido')
    
    status_text = (
        "🧠 <b>STATUS DA INTELIGÊNCIA ARTIFICIAL</b>\n\n"
        f"🤖 Modelo de Previsão: {rf_status}\n"
        f"🔍 Detector de Anomalias: {anomaly_status}\n"
        f"🌡️ Sentimento de Mercado: {sentiment}\n"
        f"📊 Score de Sentimento: {ml_models.get('sentiment_score', 'N/A')}\n"
        f"⚡ Estratégias IA Ativas: {sum(1 for k,v in STRATEGIES.items() if 'ai' in k and v['active'])}/2"
    )
    
    bot.reply_to(message, status_text)

@bot.message_handler(commands=['ai_analyze'])
def ai_analyze_command(message):
    """Análise IA de um par específico"""
    try:
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "⚠️ Use: /ai_analyze BTCUSDT")
            return
        
        symbol = args[1].upper()
        
        if symbol not in PAIRS:
            bot.reply_to(message, f"⚠️ Par {symbol} não monitorado")
            return
        
        # Obtém dados
        df = get_binance_data(symbol)
        if df is None or len(df) < 50:
            bot.reply_to(message, f"⚠️ Dados insuficientes para {symbol}")
            return
        
        # Análise IA
        recommendation = intelligent_recommendation(df, symbol)
        patterns = detect_chart_patterns(df)
        
        # Formata resposta
        analysis_text = (
            f"🔍 <b>ANÁLISE IA PARA {symbol}</b>\n\n"
            f"📈 Recomendação: <b>{recommendation['action']}</b>\n"
            f"🎯 Confiança: {recommendation['confidence']:.0%}\n"
            f"⚠️ Nível de Risco: {recommendation['risk_level']}\n"
            f"📊 RSI Atual: {calculate_rsi(df).iloc[-1]:.1f}\n\n"
            f"🔄 <b>Padrões Detectados:</b>\n"
        )
        
        for pattern, detected in patterns.items():
            if detected:
                analysis_text += f"• {pattern.replace('_', ' ').title()}: ✅\n"
        
        if not any(patterns.values()):
            analysis_text += "• Nenhum padrão significativo\n"
        
        # Adiciona razões
        if recommendation['reasons']:
            analysis_text += f"\n📝 <b>Razões:</b>\n" + "\n".join([f"• {r}" for r in recommendation['reasons'][:5]])
        
        bot.reply_to(message, analysis_text)
        
    except Exception as e:
        bot.reply_to(message, f"❌ Erro na análise: {str(e)}")

# =========================
# ATUALIZAÇÃO DO DASHBOARD PARA INCLUIR IA
# =========================
# (Manter o dashboard anterior, adicionando seções de IA)

@app.route('/ai_dashboard')
def ai_dashboard():
    """Dashboard específico para IA"""
    ai_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Dashboard IA - Crypto Bot</title>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #1a2980, #26d0ce);
                color: white;
                margin: 0;
                padding: 20px;
            }
            .container { max-width: 1200px; margin: 0 auto; }
            .back-btn {
                display: inline-block;
                margin-bottom: 20px;
                padding: 10px 20px;
                background: white;
                color: #3498db;
                text-decoration: none;
                border-radius: 8px;
                font-weight: 600;
            }
            .ai-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
                gap: 20px;
                margin-top: 20px;
            }
            .ai-card {
                background: rgba(255, 255, 255, 0.1);
                padding: 25px;
                border-radius: 15px;
                backdrop-filter: blur(10px);
                border: 1px solid rgba(255, 255, 255, 0.2);
            }
            .ai-card h3 {
                color: #4fc3f7;
                border-bottom: 2px solid #4fc3f7;
                padding-bottom: 10px;
                margin-top: 0;
            }
            .status-indicator {
                display: inline-block;
                width: 12px;
                height: 12px;
                border-radius: 50%;
                margin-right: 8px;
            }
            .status-online { background: #00e676; }
            .status-offline { background: #ff3d00; }
            .progress-bar {
                height: 10px;
                background: rgba(255, 255, 255, 0.2);
                border-radius: 5px;
                margin: 10px 0;
                overflow: hidden;
            }
            .progress-fill {
                height: 100%;
                background: linear-gradient(90deg, #00e676, #00b0ff);
                border-radius: 5px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/" class="back-btn">
                <i class="fas fa-arrow-left"></i> Voltar ao Dashboard Principal
            </a>
            <h1><i class="fas fa-brain"></i> Dashboard de Inteligência Artificial</h1>
            
            <div class="ai-grid">
                <!-- Card Status IA -->
                <div class="ai-card">
                    <h3><i class="fas fa-robot"></i> Status dos Modelos</h3>
                    <p>
                        <span class="status-indicator {{ 'status-online' if rf_status else 'status-offline' }}"></span>
                        Modelo de Previsão: {{ 'Operacional' if rf_status else 'Não treinado' }}
                    </p>
                    <p>
                        <span class="status-indicator {{ 'status-online' if anomaly_status else 'status-offline' }}"></span>
                        Detector de Anomalias: {{ 'Operacional' if anomaly_status else 'Não treinado' }}
                    </p>
                    <p>
                        <span class="status-indicator status-online"></span>
                        Análise de Sentimento: {{ sentiment }}
                    </p>
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: {{ sentiment_score }}%"></div>
                    </div>
                    <p>Score: {{ sentiment_score|round(1) }}%</p>
                </div>
                
                <!-- Card Estatísticas IA -->
                <div class="ai-card">
                    <h3><i class="fas fa-chart-line"></i> Estatísticas de IA</h3>
                    <p>📈 Sinais com IA: {{ ai_signals_count }}</p>
                    <p>🎯 Confiança Média: {{ avg_ai_confidence|round(1) }}%</p>
                    <p>⚡ Estratégias IA Ativas: {{ active_ai_strategies }}</p>
                    <p>🔄 Último Treinamento: {{ last_training|default('Nunca') }}</p>
                </div>
                
                <!-- Card Recomendações Atuais -->
                <div class="ai-card">
                    <h3><i class="fas fa-lightbulb"></i> Recomendações IA</h3>
                    {% for rec in current_recommendations %}
                    <div style="margin-bottom: 15px; padding: 10px; background: rgba(0,0,0,0.2); border-radius: 8px;">
                        <strong>{{ rec.symbol }}</strong>: {{ rec.action }}
                        <br><small>Confiança: {{ rec.confidence|round(0) }}% | Risco: {{ rec.risk_level }}</small>
                    </div>
                    {% endfor %}
                </div>
                
                <!-- Card Controles IA -->
                <div class="ai-card">
                    <h3><i class="fas fa-cogs"></i> Controles IA</h3>
                    <p>
                        <a href="/train_all_models" style="color: #00e676; text-decoration: none;">
                            <i class="fas fa-graduation-cap"></i> Treinar Todos os Modelos
                        </a>
                    </p>
                    <p>
                        <a href="/update_sentiment" style="color: #00b0ff; text-decoration: none;">
                            <i class="fas fa-sync-alt"></i> Atualizar Análise de Sentimento
                        </a>
                    </p>
                    <p>
                        <form action="/toggle_ai_strategy" method="post" style="margin-top: 15px;">
                            <label style="display: block; margin-bottom: 5px;">
                                <input type="checkbox" name="ai_predictor" {{ 'checked' if strategies.ai_predictor.active }}>
                                Preditor IA
                            </label>
                            <label style="display: block; margin-bottom: 5px;">
                                <input type="checkbox" name="sentiment" {{ 'checked' if strategies.sentiment.active }}>
                                Análise de Sentimento
                            </label>
                            <button type="submit" style="margin-top: 10px; padding: 8px 15px; background: #00b0ff; border: none; color: white; border-radius: 5px;">
                                Atualizar
                            </button>
                        </form>
                    </p>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    
    # Coleta dados para o dashboard IA
    rf_status = ml_models['random_forest'] is not None
    anomaly_status = ml_models['anomaly_detector'] is not None
    sentiment = ml_models.get('market_sentiment', 'NEUTRAL')
    sentiment_score = ml_models.get('sentiment_score', 50)
    
    # Sinais com IA
    ai_signals = [s for s in last_signals if s.get('ai_confidence', 0) > 0]
    ai_signals_count = len(ai_signals)
    avg_ai_confidence = np.mean([s.get('ai_confidence', 0) for s in ai_signals]) * 100 if ai_signals else 0
    
    # Estratégias IA ativas
    active_ai_strategies = sum(1 for k, v in STRATEGIES.items() if 'ai' in k and v['active'])
    
    # Último treinamento (simulado - na prática seria do arquivo salvo)
    last_training = None
    
    # Recomendações atuais
    current_recommendations = []
    for pair in PAIRS[:5]:  # Apenas 5 principais
        try:
            df = get_binance_data(pair)
            if df is not None and len(df) > 50:
                rec = intelligent_recommendation(df, pair)
                current_recommendations.append({
                    'symbol': pair,
                    'action': rec['action'],
                    'confidence': rec['confidence'] * 100,
                    'risk_level': rec['risk_level']
                })
        except:
            pass
    
    return render_template_string(
        ai_html,
        rf_status=rf_status,
        anomaly_status=anomaly_status,
        sentiment=sentiment,
        sentiment_score=sentiment_score,
        ai_signals_count=ai_signals_count,
        avg_ai_confidence=avg_ai_confidence,
        active_ai_strategies=active_ai_strategies,
        last_training=last_training,
        current_recommendations=current_recommendations,
        strategies=STRATEGIES
    )

# =========================
# FUNÇÕES DE TREINAMENTO AGENDADO
# =========================
def schedule_ai_training():
    """Agenda treinamento periódico dos modelos de IA"""
    # Treina modelos uma vez ao dia
    schedule.every().day.at("02:00").do(lambda: train_all_models())
    
    # Atualiza sentimento a cada hora
    schedule.every().hour.do(lambda: analyze_market_sentiment())

def train_all_models():
    """Treina modelos para todos os pares"""
    logger.info("Iniciando treinamento periódico de modelos IA...")
    for pair in PAIRS[:5]:  # Treina apenas para 5 principais
        try:
            train_ai_model(pair)
            time.sleep(10)  # Delay entre treinamentos
        except Exception as e:
            logger.error(f"Erro ao treinar {pair}: {e}")

# =========================
# ATUALIZAÇÃO DA FUNÇÃO MAIN
# =========================
def main():
    """Função principal atualizada com IA"""
    logger.info("=" * 50)
    logger.info("INICIANDO CRYPTO SCALPING BOT COM IA")
    logger.info("=" * 50)
    
    # Inicializa IA
    logger.info("🧠 Inicializando sistemas de IA...")
    analyze_market_sentiment()  # Primeira análise de sentimento
    
    # Agenda treinamentos automáticos
    schedule_ai_training()
    
    # Treina modelos em background (thread separada)
    def train_in_background():
        time.sleep(60)  # Espera 1 minuto após iniciar
        train_all_models()
    
    threading.Thread(target=train_in_background, daemon=True).start()
    
    # Resto do código de inicialização permanece igual...
    logger.info(f"Pares monitorados: {len(PAIRS)}")
    logger.info(f"Estratégias IA ativas: {sum(1 for s in STRATEGIES.values() if s['active'])}")
    logger.info(f"Dashboard: http://localhost:8080")
    logger.info(f"Dashboard IA: http://localhost:8080/ai_dashboard")
    logger.info("=" * 50)
    
    try:
        startup_msg = (
            "🤖 <b>CRYPTO SCALPING BOT COM IA INICIADO</b>\n\n"
            f"🧠 IA Status: Inicializado\n"
            f"📊 Sentimento: {ml_models['market_sentiment']}\n"
            f"📈 Pares: {len(PAIRS)}\n"
            f"⚡ Estratégias: {sum(1 for s in STRATEGIES.values() if s['active'])}/5\n"
            f"🌐 Dashboard IA: Disponível\n\n"
            "✅ Sistema IA operacional e aprendendo..."
        )
        bot.send_message(CHAT_ID, startup_msg)
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem de início: {e}")
    
    # Inicia threads (código anterior mantido)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    telegram_thread = threading.Thread(target=run_telegram_bot, daemon=True)
    
    flask_thread.start()
    telegram_thread.start()
    
    # Executa verificador de sinais na thread principal
    try:
        run_signal_checker()
    except KeyboardInterrupt:
        logger.info("\nBot encerrado pelo usuário")
        shutdown_msg = "🛑 <b>Bot encerrado</b>\nSistema IA desligado."
        try:
            bot.send_message(CHAT_ID, shutdown_msg)
        except:
            pass
    except Exception as e:
        logger.error(f"Erro fatal: {e}")

# =========================
# ATUALIZAÇÃO DAS FUNÇÕES EXISTENTES
# =========================
# Manter todas as funções anteriores (get_binance_data, calculate_rsi, etc.)
# apenas adicionando as importações necessárias no início

# Adicionar estas importações no topo do arquivo se não existirem:
# from sklearn.ensemble import RandomForestClassifier, IsolationForest
# from sklearn.preprocessing import StandardScaler
# import numpy as np
# import yfinance as yf

if __name__ == "__main__":
    # Instalar dependências adicionais se necessário
    # pip install scikit-learn yfinance scipy
    
    main()
