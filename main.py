import random
import threading
import time
from collections import deque
from datetime import datetime
from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

# ===================== DASHBOARD =====================

DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-br">
<head>
<meta charset="UTF-8">
<title>Dashboard de Sinais</title>
<style>
body { font-family: Arial; background:#0f172a; color:#e5e7eb; margin:20px }
.card { background:#020617; padding:15px; border-radius:10px; margin-bottom:10px }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:10px }
h1 { margin-bottom:10px }
.win { color:#22c55e }
.loss { color:#ef4444 }
</style>
</head>
<body>

<h1>📊 Dashboard de Sinais</h1>

<div class="grid">
  <div class="card">Total sinais: <b id="total"></b></div>
  <div class="card">Winrate: <b id="winrate"></b></div>
  <div class="card">Winrate hoje: <b id="winrate_hoje"></b></div>
  <div class="card">Profit: <b id="profit"></b></div>
  <div class="card">Em aberto: <b id="abertos"></b></div>
  <div class="card">Melhor sequência: <b id="melhor"></b></div>
  <div class="card">Pior sequência: <b id="pior"></b></div>
</div>

<h2>📜 Histórico</h2>
<div id="historico"></div>

<script>
async function atualizar(){
  const r = await fetch('/api/estatisticas');
  const d = await r.json();

  total.innerText = d.total_sinais;
  winrate.innerText = d.winrate_formatado;
  winrate_hoje.innerText = d.winrate_hoje_formatado;
  profit.innerText = d.profit_total_formatado;
  abertos.innerText = d.sinais_em_aberto;
  melhor.innerText = d.melhor_sequencia;
  pior.innerText = d.pior_sequencia;

  const h = await fetch('/api/historico');
  const hist = await h.json();
  historico.innerHTML = '';
  hist.reverse().forEach(s=>{
    historico.innerHTML += `
      <div class="card">
        ${s.ativo} | ${s.direcao} |
        <span class="${s.resultado==='WIN'?'win':'loss'}">${s.resultado || 'ABERTO'}</span>
        | ${s.profit}
      </div>`;
  })
}

setInterval(atualizar, 2000);
atualizar();
</script>

</body>
</html>
"""

# ===================== SISTEMA =====================

class SistemaWinrate:
    def __init__(self):
        self.lock = threading.Lock()
        self.sinais = deque(maxlen=100)
        self.est = {
            "total_sinais": 0,
            "sinais_vencedores": 0,
            "sinais_perdedores": 0,
            "winrate": 0.0,
            "profit_total": 0.0,
            "melhor_sequencia": 0,
            "pior_sequencia": 0,
            "sinais_hoje": 0,
            "winrate_hoje": 0.0
        }

    def novo_sinal(self):
        with self.lock:
            sinal = {
                "id": int(time.time()*1000),
                "ativo": random.choice(["BTCUSDT","ETHUSDT","EURUSD"]),
                "direcao": random.choice(["CALL","PUT"]),
                "timestamp": datetime.now().isoformat(),
                "resultado": None,
                "profit": 0.0
            }
            self.sinais.append(sinal)
            self.est["total_sinais"] += 1
            return sinal

    def fechar_sinal(self, sinal):
        with self.lock:
            win = random.choice([True, False])
            profit = random.uniform(1,4) if win else random.uniform(-4,-1)

            sinal["resultado"] = "WIN" if win else "LOSS"
            sinal["profit"] = round(profit,2)

            if win:
                self.est["sinais_vencedores"] += 1
            else:
                self.est["sinais_perdedores"] += 1

            self.est["profit_total"] += profit
            self._recalcular()

    def _recalcular(self):
        fechados = self.est["sinais_vencedores"] + self.est["sinais_perdedores"]
        if fechados:
            self.est["winrate"] = self.est["sinais_vencedores"] / fechados * 100

        hoje = datetime.now().date()
        sinais_hoje = [s for s in self.sinais if datetime.fromisoformat(s["timestamp"]).date()==hoje]
        fechados_hoje = [s for s in sinais_hoje if s["resultado"]]
        self.est["sinais_hoje"] = len(sinais_hoje)

        if fechados_hoje:
            wins = sum(1 for s in fechados_hoje if s["resultado"]=="WIN")
            self.est["winrate_hoje"] = wins/len(fechados_hoje)*100

        seq=melhor=pior=0
        for s in self.sinais:
            if s["resultado"]=="WIN":
                seq = seq+1 if seq>=0 else 1
            elif s["resultado"]=="LOSS":
                seq = seq-1 if seq<=0 else -1
            melhor=max(melhor,seq)
            pior=min(pior,seq)

        self.est["melhor_sequencia"]=melhor
        self.est["pior_sequencia"]=abs(pior)

    def stats(self):
        with self.lock:
            return {
                **self.est,
                "winrate_formatado": f"{self.est['winrate']:.1f}%",
                "winrate_hoje_formatado": f"{self.est['winrate_hoje']:.1f}%",
                "profit_total_formatado": f"${self.est['profit_total']:+.2f}",
                "sinais_em_aberto": self.est["total_sinais"]-(self.est["sinais_vencedores"]+self.est["sinais_perdedores"])
            }

    def historico(self):
        with self.lock:
            return list(self.sinais)

sistema = SistemaWinrate()

# ===================== THREAD =====================

def simulador():
    while True:
        s = sistema.novo_sinal()
        time.sleep(random.randint(5,10))
        sistema.fechar_sinal(s)
        time.sleep(random.randint(5,10))

threading.Thread(target=simulador, daemon=True).start()

# ===================== ROTAS =====================

@app.route("/")
def index():
    return render_template_string(DASHBOARD_TEMPLATE)

@app.route("/api/estatisticas")
def estatisticas():
    return jsonify(sistema.stats())

@app.route("/api/historico")
def historico():
    return jsonify(sistema.historico())

# ===================== START =====================

if __name__ == "__main__":
    app.run(debug=True, threaded=True)
