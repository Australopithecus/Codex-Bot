from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import json
import os

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from .logging_db import read_latest_equity, read_latest_positions, read_latest_trades, read_latest_advisor_reports


def create_app(db_path: str) -> FastAPI:
    app = FastAPI(title="Broker Bot Dashboard")
    api_token = os.getenv("API_TOKEN", "").strip()

    def _check_token(request: Request) -> None:
        if not api_token:
            return
        header_token = request.headers.get("X-API-Token")
        query_token = request.query_params.get("token")
        if header_token == api_token or query_token == api_token:
            return
        raise HTTPException(status_code=401, detail="Unauthorized")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _dashboard_html()

    @app.get("/api/summary")
    def summary(request: Request) -> JSONResponse:
        _check_token(request)
        rows = read_latest_equity(db_path, limit=1)
        if not rows:
            return JSONResponse(
                {
                    "status": "empty",
                    "message": "No equity snapshots yet. Run the bot to log data.",
                }
            )
        ts, equity, cash, portfolio, spy_value = rows[0]
        return JSONResponse(
            {
                "status": "ok",
                "ts": ts,
                "equity": equity,
                "cash": cash,
                "portfolio": portfolio,
                "spy": spy_value,
            }
        )

    @app.get("/api/equity")
    def equity(request: Request) -> JSONResponse:
        _check_token(request)
        rows = read_latest_equity(db_path, limit=180)
        rows = list(reversed(rows))
        data = [
            {
                "ts": row[0],
                "equity": row[1],
                "spy": row[4],
            }
            for row in rows
        ]
        return JSONResponse({"data": data})

    @app.get("/api/positions")
    def positions(request: Request) -> JSONResponse:
        _check_token(request)
        rows = read_latest_positions(db_path, limit=200)
        data = [
            {
                "symbol": row[0],
                "qty": row[1],
                "avg_entry": row[2],
                "market_value": row[3],
                "unreal_pl": row[4],
            }
            for row in rows
        ]
        return JSONResponse({"data": data})

    @app.get("/api/trades")
    def trades(request: Request) -> JSONResponse:
        _check_token(request)
        rows = read_latest_trades(db_path, limit=200)
        data = [
            {
                "ts": row[0],
                "symbol": row[1],
                "side": row[2],
                "qty": row[3],
                "price": row[4],
                "status": row[5],
            }
            for row in rows
        ]
        return JSONResponse({"data": data})

    @app.get("/api/advisor")
    def advisor(request: Request) -> JSONResponse:
        _check_token(request)
        rows = read_latest_advisor_reports(db_path, limit=10)
        data = []
        for row in rows:
            data.append(
                {
                    "ts": row[0],
                    "headline": row[1],
                    "summary": row[2],
                    "suggestions": json.loads(row[3]) if row[3] else [],
                    "metrics": json.loads(row[4]) if row[4] else {},
                    "overrides": json.loads(row[5]) if row[5] else {},
                }
            )
        return JSONResponse({"data": data})

    return app


def _dashboard_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Broker Bot Dashboard</title>
  <style>
    :root {
      --bg: #0b1020;
      --panel: #111827;
      --muted: #9ca3af;
      --text: #e5e7eb;
      --accent: #22d3ee;
      --accent-2: #a78bfa;
      --green: #34d399;
      --red: #f87171;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Avenir", "Gill Sans", "Helvetica Neue", sans-serif;
      background: radial-gradient(circle at top, #172554, var(--bg));
      color: var(--text);
      min-height: 100vh;
      display: flex;
      align-items: stretch;
      justify-content: center;
      padding: 24px;
    }
    .container {
      width: min(1100px, 100%);
      display: grid;
      grid-template-rows: auto auto 1fr;
      gap: 20px;
    }
    header {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    header h1 {
      margin: 0;
      font-size: 28px;
      letter-spacing: 0.5px;
    }
    header p { margin: 0; color: var(--muted); }

    .summary {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
    }
    .card {
      background: linear-gradient(145deg, #111827, #0f172a);
      border: 1px solid #1f2937;
      padding: 14px 16px;
      border-radius: 14px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.3);
    }
    .card h3 { margin: 0; font-size: 12px; color: var(--muted); letter-spacing: 0.8px; text-transform: uppercase; }
    .card .value { margin-top: 6px; font-size: 20px; font-weight: 600; }

    .grid {
      display: grid;
      grid-template-columns: 2fr 1fr;
      gap: 16px;
      align-items: stretch;
    }

    .panel {
      background: var(--panel);
      border: 1px solid #1f2937;
      border-radius: 18px;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .panel h2 { margin: 0; font-size: 16px; color: var(--text); }

    canvas { width: 100%; height: 240px; }

    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }
    th, td {
      text-align: left;
      padding: 6px 8px;
      border-bottom: 1px solid #1f2937;
    }
    th { color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }

    .pill {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 600;
    }
    .buy { background: rgba(52, 211, 153, 0.2); color: var(--green); }
    .sell { background: rgba(248, 113, 113, 0.2); color: var(--red); }

    .muted { color: var(--muted); }

    @media (max-width: 900px) {
      .summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>Broker Bot Dashboard</h1>
      <p>Local paper-trading monitor • Auto-refreshes every 10s</p>
    </header>

    <section class="summary">
      <div class="card"><h3>Equity</h3><div class="value" id="equity">--</div></div>
      <div class="card"><h3>Cash</h3><div class="value" id="cash">--</div></div>
      <div class="card"><h3>Portfolio</h3><div class="value" id="portfolio">--</div></div>
      <div class="card"><h3>SPY Close</h3><div class="value" id="spy">--</div></div>
      <div class="card"><h3>Alpha 20D</h3><div class="value" id="alpha20">--</div></div>
      <div class="card"><h3>Tracking Error</h3><div class="value" id="trackErr">--</div></div>
    </section>

    <section class="grid">
      <div class="panel">
        <h2>Equity Curve</h2>
        <canvas id="equityChart" width="900" height="240"></canvas>
        <div class="muted" id="equityHint"></div>
      </div>
      <div class="panel">
        <h2>Positions</h2>
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Qty</th>
              <th>Avg</th>
              <th>Value</th>
              <th>Unreal</th>
            </tr>
          </thead>
          <tbody id="positionsBody"></tbody>
        </table>
      </div>
    </section>

    <section class="panel">
      <h2>Recent Trades</h2>
      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>Symbol</th>
            <th>Side</th>
            <th>Qty</th>
            <th>Price</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody id="tradesBody"></tbody>
      </table>
    </section>

    <section class="panel">
      <h2>Advisor Reports</h2>
      <div id="advisorReports" class="muted">No reports yet.</div>
    </section>
  </div>

<script>
const fmt = (num) => {
  if (num === null || num === undefined) return "--";
  return "$" + Number(num).toLocaleString(undefined, { maximumFractionDigits: 2 });
};
const pct = (num) => {
  if (num === null || num === undefined || Number.isNaN(num)) return "--";
  return (num * 100).toFixed(2) + "%";
};
const stdev = (arr) => {
  if (!arr.length || arr.length < 2) return 0;
  const mean = arr.reduce((a, b) => a + b, 0) / arr.length;
  const variance = arr.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / (arr.length - 1);
  return Math.sqrt(variance);
};

const tokenParam = new URLSearchParams(window.location.search).get('token');
const apiHeaders = tokenParam ? { 'X-API-Token': tokenParam } : {};

async function loadSummary() {
  const res = await fetch('/api/summary', { headers: apiHeaders });
  const data = await res.json();
  if (data.status !== 'ok') {
    document.getElementById('equity').textContent = '--';
    document.getElementById('cash').textContent = '--';
    document.getElementById('portfolio').textContent = '--';
    document.getElementById('spy').textContent = '--';
    return;
  }
  document.getElementById('equity').textContent = fmt(data.equity);
  document.getElementById('cash').textContent = fmt(data.cash);
  document.getElementById('portfolio').textContent = fmt(data.portfolio);
  document.getElementById('spy').textContent = data.spy ? fmt(data.spy) : '--';
}

async function loadEquity() {
  const res = await fetch('/api/equity', { headers: apiHeaders });
  const data = await res.json();
  const points = data.data || [];
  const canvas = document.getElementById('equityChart');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#0f172a';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  if (points.length < 2) {
    ctx.fillStyle = '#94a3b8';
    ctx.font = '14px Helvetica';
    ctx.fillText('No equity history yet.', 20, 30);
    document.getElementById('equityHint').textContent = '';
    return;
  }
  const values = points.map(p => p.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = 20;
  const scaleX = (i) => pad + (canvas.width - pad * 2) * (i / (values.length - 1));
  const scaleY = (v) => canvas.height - pad - (canvas.height - pad * 2) * ((v - min) / (max - min || 1));

  ctx.strokeStyle = '#22d3ee';
  ctx.lineWidth = 2;
  ctx.beginPath();
  values.forEach((v, i) => {
    const x = scaleX(i);
    const y = scaleY(v);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // SPY curve normalized to strategy start
  const spySeries = points.map(p => p.spy).filter(v => v !== null && v !== undefined);
  if (spySeries.length > 1) {
    const spyStart = points[0].spy || spySeries[0];
    const eqStart = values[0];
    const spyNorm = points.map(p => {
      if (p.spy === null || p.spy === undefined || spyStart === 0) return null;
      return (p.spy / spyStart) * eqStart;
    });
    ctx.strokeStyle = '#a78bfa';
    ctx.lineWidth = 2;
    ctx.beginPath();
    spyNorm.forEach((v, i) => {
      if (v === null) return;
      const x = scaleX(i);
      const y = scaleY(v);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  document.getElementById('equityHint').textContent = `Min: ${fmt(min)} • Max: ${fmt(max)} • Cyan: Bot • Purple: SPY`;

  // Alpha + tracking error (20D) if we have SPY values
  const aligned = points.filter(p => p.spy !== null && p.spy !== undefined);
  if (aligned.length >= 21) {
    const window = aligned.slice(-21);
    const botRet = (window[window.length - 1].equity / window[0].equity) - 1;
    const spyRet = (window[window.length - 1].spy / window[0].spy) - 1;
    const alpha = botRet - spyRet;
    const diffs = [];
    for (let i = 1; i < window.length; i++) {
      const br = (window[i].equity / window[i - 1].equity) - 1;
      const sr = (window[i].spy / window[i - 1].spy) - 1;
      diffs.push(br - sr);
    }
    const te = stdev(diffs);
    document.getElementById('alpha20').textContent = pct(alpha);
    document.getElementById('trackErr').textContent = pct(te);
  } else {
    document.getElementById('alpha20').textContent = '--';
    document.getElementById('trackErr').textContent = '--';
  }
}

async function loadPositions() {
  const res = await fetch('/api/positions', { headers: apiHeaders });
  const data = await res.json();
  const body = document.getElementById('positionsBody');
  body.innerHTML = '';
  (data.data || []).forEach(row => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${row.symbol}</td>
      <td>${Number(row.qty).toFixed(2)}</td>
      <td>${fmt(row.avg_entry)}</td>
      <td>${fmt(row.market_value)}</td>
      <td>${fmt(row.unreal_pl)}</td>
    `;
    body.appendChild(tr);
  });
}

async function loadTrades() {
  const res = await fetch('/api/trades', { headers: apiHeaders });
  const data = await res.json();
  const body = document.getElementById('tradesBody');
  body.innerHTML = '';
  (data.data || []).forEach(row => {
    const tr = document.createElement('tr');
    const sideClass = row.side === 'buy' ? 'buy' : 'sell';
    tr.innerHTML = `
      <td>${row.ts}</td>
      <td>${row.symbol}</td>
      <td><span class="pill ${sideClass}">${row.side}</span></td>
      <td>${Number(row.qty).toFixed(2)}</td>
      <td>${fmt(row.price)}</td>
      <td>${row.status || ''}</td>
    `;
    body.appendChild(tr);
  });
}

async function loadAdvisor() {
  const res = await fetch('/api/advisor', { headers: apiHeaders });
  const data = await res.json();
  const reports = data.data || [];
  const container = document.getElementById('advisorReports');
  if (!reports.length) {
    container.textContent = 'No reports yet.';
    return;
  }
  container.innerHTML = '';
  reports.slice(0, 5).forEach(report => {
    const div = document.createElement('div');
    div.className = 'card';
    div.style.marginBottom = '10px';
    const suggestions = (report.suggestions || []).map(s => `• ${s}`).join('<br />');
    const overrideKeys = report.overrides ? Object.keys(report.overrides) : [];
    const overrides = overrideKeys.length
      ? `Overrides: ${overrideKeys.map(k => `${k}=${report.overrides[k]}`).join(', ')}`
      : '';
    div.innerHTML = `
      <strong>${report.headline}</strong> <span class="muted">(${report.ts})</span><br />
      ${report.summary}<br />
      <span class="muted">${suggestions}</span><br />
      <span class="muted">${overrides}</span>
    `;
    container.appendChild(div);
  });
}

async function refreshAll() {
  await Promise.all([loadSummary(), loadEquity(), loadPositions(), loadTrades(), loadAdvisor()]);
}

refreshAll();
setInterval(refreshAll, 10000);
</script>
</body>
</html>"""
