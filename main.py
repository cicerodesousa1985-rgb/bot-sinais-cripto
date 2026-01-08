import os
import time
import threading
import logging
import random
from datetime import datetime
from flask import Flask, jsonify, render_template_string
from binance.client import Client
from binance.enums import *
import pandas as pd

# =========================
# CONFIGURAÇÃO
# =========================
app = Flask(__name__)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("FatPig")

PORT = int(os.getenv("PORT", "10000"))
BOT_INTERVAL = 300  # 5 minutos

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")

client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]

MARGIN_PER_TRADE = 1.0
TP_PERCENT = 0.02
SL_PERCENT = 0.01

PRECISION = {
    "BTCUSDT": 3,
    "ETHUSDT": 3,
    "BNBUSDT": 2,
    "SOLUSDT": 1
}

# =========================
# SETUP BINANCE
# =========================
for sym in SYMBOLS:
    try:
        client.futures_change_margin_type(symbol=sym, marginType='ISOLATED')
    except:
        pass

# =========================
# WINRATE REAL (PNL BINANCE)
# =========================
class SistemaWinrate:
    def __init__(self):
        self.cache = None
        self.cache_time = 0

    def get_estatisticas(self):
        now = time.time()
        if self.cache and now - self.cache_time < 30:
            return self.cache

        try:
            trades_all = []
            for sym in SYMBOLS:
                trades_all += client.futures_account_trade_list(symbol=sym, limit=500)

            if not trades_all:
                return self._fallback()

            df = pd.DataFrame(trades_all)
            df["pnl"] = pd.to_numeric(df["realizedPnl"], errors="coerce")
            df = df[df["pnl"] != 0]
            df["time"] = pd.to_datetime(df["time"], unit="ms")

            total = len(df)
            wins = len(df[df["pnl"] > 0])
            losses = total - wins
            winrate = (wins / total * 100) if total else 0
            profit = df["pnl"].sum()

            hoje = datetime.now().date()
            df_hoje = df[df["time"].dt.date == hoje]
            total_hoje = len(df_hoje)
            wins_hoje = len(df_hoje[df_hoje["pnl"] > 0])
            winrate_hoje = (wins_hoje / total_hoje * 100) if total_hoje else 0

            stats = {
                "total_fechados": total,
                "sinais_vencedores": wins,
                "sinais_perdedores": losses,
                "winrate": winrate,
                "winrate_formatado": f"{winrate:.1f}%",
                "profit_total": profit,
                "profit_total_formatado": f"${profit:+.2f}",
                "sinais_hoje": total_hoje,
                "winrate_hoje_formatado": f"{winrate_hoje:.1f}%",
                "ultima_atualizacao": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            }

        except Exception as e:
            logger.error(e)
            stats = self._fallback()

        self.cache = stats
        self.cache_time = now
        return stats

    def _fallback(self):
        return {
            "total_fechados": 0,
            "sinais_vencedores": 0,
            "sinais_perdedores": 0,
            "winrate": 0,
            "winrate_formatado": "0.0%",
            "profit_total": 0,
            "profit_total_formatado": "$0.00",
            "sinais_hoje": 0,
            "winrate_hoje_formatado": "0.0%",
            "ultima_atualizacao": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        }

sistema_winrate = SistemaWinrate()

# =========================
# TRADE REAL FUTURES
# =========================
def preco(simbolo):
    return float(client.futures_mark_price(symbol=simbolo)["markPrice"])

def executar_trade(simbolo, direcao):
    try:
        positions = client.futures_position_information(symbol=simbolo)
        if any(float(p["positionAmt"]) != 0 for p in positions):
            return

        trades = client.futures_account_trade_list(symbol=simbolo, limit=50)
        fechados = [t for t in trades if float(t["realizedPnl"]) != 0]
        winrate = sum(1 for t in fechados if float(t["realizedPnl"]) > 0) / len(fechados) if fechados else 0.5
        leverage = max(1, min(10, int(winrate * 10)))

        client.futures_change_leverage(symbol=simbolo, leverage=leverage)

        price = preco(simbolo)
        qty = round((MARGIN_PER_TRADE * leverage) / price, PRECISION[simbolo])

        side = SIDE_BUY if direcao == "COMPRA" else SIDE_SELL
        close_side = SIDE_SELL if side == SIDE_BUY else SIDE_BUY

        client.futures_create_order(
            symbol=simbolo,
            side=side,
            type=ORDER_TYPE_MARKET,
            quantity=qty
        )

        tp = price * (1 + TP_PERCENT if side == SIDE_BUY else 1 - TP_PERCENT)
        sl = price * (1 - SL_PERCENT if side == SIDE_BUY else 1 + SL_PERCENT)

        client.futures_create_order(
            symbol=simbolo,
            side=close_side,
            type=ORDER_TYPE_TAKE_PROFIT_MARKET,
            stopPrice=round(tp, 2),
            closePosition=True
        )

        client.futures_create_order(
            symbol=simbolo,
            side=close_side,
            type=ORDER_TYPE_STOP_MARKET,
            stopPrice=round(sl, 2),
            closePosition=True
        )

        logger.info(f"TRADE {direcao} {simbolo} {leverage}x")

    except Exception as e:
        logger.error(e)

# =========================
# WORKER
# =========================
def worker():
    logger.info("🤖 BOT FUTURES ATIVO")
    while True:
        for s in SYMBOLS:
            if random.random() < 0.25:
                executar_trade(s, "COMPRA" if random.random() < 0.5 else "VENDA")
            time.sleep(5)
        time.sleep(BOT_INTERVAL)

# =========================
# DASHBOARD (SEM ERRO)
# =========================
DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>FatPig Signals</title>
<style>
body{background:#0a0a0a;color:#fff;font-family:Arial}
.card{background:#111;padding:15px;margin:10px;border-radius:8px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}
h1{color:#00ff88}
</style>
</head>
<body>
<h1>🐷 FatPig Signals – Futures REAL</h1>

<div class="grid">
  <div class="card">Winrate: {{ winrate_stats.winrate_formatado }}</div>
  <div class="card">Lucro: {{ winrate_stats.profit_total_formatado }}</div>
  <div class="card">Hoje: {{ winrate_stats.winrate_hoje_formatado }}</div>
  <div class="card">Trades: {{ winrate_stats.total_fechados }}</div>
</div>

<p>Última atualização: {{ winrate_stats.ultima_atualizacao }}</p>

<script>
setTimeout(()=>location.reload(),30000);
</script>
</body>
</html>
"""

# =========================
# ROTAS
# =========================
@app.route("/")
def dashboard():
    return render_template_string(
        DASHBOARD_TEMPLATE,
        winrate_stats=sistema_winrate.get_estatisticas()
    )

@app.route("/api/estatisticas")
def api_stats():
    return jsonify(sistema_winrate.get_estatisticas())

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
