import os
import threading
import requests
from datetime import datetime
from flask import Flask, jsonify, render_template_string
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# =========================
# CONFIG
# =========================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
FOOTBALL_DATA_TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN")

HEADERS = {
    "X-Auth-Token": FOOTBALL_DATA_TOKEN
}

# =========================
# FLASK DASHBOARD
# =========================
app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Dashboard Futebol</title>
    <style>
        body { font-family: Arial; background: #0f172a; color: #fff; text-align: center; }
        .card { background: #1e293b; padding: 20px; margin: 20px auto; width: 90%; max-width: 500px; border-radius: 10px; }
        h1 { color: #38bdf8; }
    </style>
</head>
<body>
    <h1>⚽ Dashboard Futebol</h1>
    <div class="card">
        <p>Status do Bot: <b>ONLINE</b></p>
        <p>Última atualização: {{hora}}</p>
    </div>
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(HTML, hora=datetime.now().strftime("%d/%m/%Y %H:%M:%S"))

@app.route("/jogos")
def jogos_api():
    hoje = datetime.utcnow().strftime("%Y-%m-%d")
    url = f"https://api.football-data.org/v4/matches?dateFrom={hoje}&dateTo={hoje}"
    r = requests.get(url, headers=HEADERS)
    return jsonify(r.json())

# =========================
# TELEGRAM BOT
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚽ Bot Futebol\n\n"
        "/jogos - Jogos de hoje\n"
        "/tabela - Classificação Premier League"
    )

async def jogos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    hoje = datetime.utcnow().strftime("%Y-%m-%d")
    url = f"https://api.football-data.org/v4/matches?dateFrom={hoje}&dateTo={hoje}"
    r = requests.get(url, headers=HEADERS)
    data = r.json()

    if not data.get("matches"):
        await update.message.reply_text("Nenhum jogo hoje.")
        return

    texto = "⚽ Jogos de Hoje:\n\n"
    for j in data["matches"][:10]:
        texto += f"{j['homeTeam']['name']} x {j['awayTeam']['name']}\n"

    await update.message.reply_text(texto)

async def tabela(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = "https://api.football-data.org/v4/competitions/2021/standings"
    r = requests.get(url, headers=HEADERS)
    tabela = r.json()["standings"][0]["table"]

    texto = "🏆 Premier League\n\n"
    for t in tabela[:10]:
        texto += f"{t['position']}º {t['team']['name']} - {t['points']} pts\n"

    await update.message.reply_text(texto)

def start_bot():
    bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(CommandHandler("jogos", jogos))
    bot.add_handler(CommandHandler("tabela", tabela))
    bot.run_polling()

# =========================
# START EVERYTHING
# =========================
if __name__ == "__main__":
    threading.Thread(target=start_bot).start()
    app.run(host="0.0.0.0", port=10000)
