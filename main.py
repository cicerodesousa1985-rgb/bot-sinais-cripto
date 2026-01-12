import React, { useState, useEffect } from "react";
import {
  LineChart,
  Line,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

const mockEquityData = [
  { time: "01 Jan", equity: 1000 },
  { time: "02 Jan", equity: 1020 },
  { time: "03 Jan", equity: 1045 },
  { time: "04 Jan", equity: 1030 },
  { time: "05 Jan", equity: 1100 },
  { time: "06 Jan", equity: 1150 },
  { time: "07 Jan", equity: 1200 },
];

export default function Dashboard() {
  const [winrate, setWinrate] = useState(0);
  const [equity, setEquity] = useState(0);
  const [equityData, setEquityData] = useState([]);

  // Simular fetch de dados
  useEffect(() => {
    // Aqui você pode substituir pelo fetch real da API/backend
    setWinrate(85.5);
    setEquity(1200);
    setEquityData(mockEquityData);
  }, []);

  return (
    <div style={styles.container}>
      <header style={styles.header}>
        <h1 style={{ margin: 0, color: "#0ef" }}>FAT PIG PRO</h1>
        <div style={styles.stats}>
          <div style={styles.statBox}>
            <span style={styles.statLabel}>Winrate</span>
            <span style={styles.statValue}>{winrate.toFixed(2)}%</span>
          </div>
          <div style={styles.statBox}>
            <span style={styles.statLabel}>Equity</span>
            <span style={styles.statValue}>${equity.toLocaleString()}</span>
          </div>
        </div>
      </header>

      <section style={styles.chartSection}>
        <h2 style={{ color: "#0ef" }}>Equity Curve</h2>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={equityData} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
            <CartesianGrid stroke="#222" strokeDasharray="3 3" />
            <XAxis dataKey="time" stroke="#aaa" />
            <YAxis stroke="#aaa" />
            <Tooltip
              contentStyle={{ backgroundColor: "#111", borderRadius: 6 }}
              labelStyle={{ color: "#0ef" }}
              itemStyle={{ color: "#0ef" }}
            />
            <Legend />
            <Line type="monotone" dataKey="equity" stroke="#0ef" strokeWidth={2} dot={{ r: 4 }} />
          </LineChart>
        </ResponsiveContainer>
      </section>

      <footer style={styles.footer}>
        <small style={{ color: "#555" }}>
          Desenvolvido por Fat Pig Pro - Dashboard 2026
        </small>
      </footer>
    </div>
  );
}

const styles = {
  container: {
    backgroundColor: "#121212",
    minHeight: "100vh",
    padding: "20px 40px",
    fontFamily: "'Segoe UI', Tahoma, Geneva, Verdana, sans-serif",
  },
  header: {
    marginBottom: 30,
    borderBottom: "1px solid #222",
    paddingBottom: 15,
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    flexWrap: "wrap",
  },
  stats: {
    display: "flex",
    gap: "30px",
  },
  statBox: {
    backgroundColor: "#1f1f1f",
    borderRadius: 10,
    padding: "10px 20px",
    minWidth: 100,
    textAlign: "center",
  },
  statLabel: {
    display: "block",
    fontSize: 14,
    color: "#888",
    marginBottom: 6,
  },
  statValue: {
    fontSize: 22,
    fontWeight: "bold",
    color: "#0ef",
  },
  chartSection: {
    backgroundColor: "#1f1f1f",
    padding: 20,
    borderRadius: 15,
  },
  footer: {
    marginTop: 40,
    textAlign: "center",
  },
};
