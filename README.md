# Broker Bot (Paper Trading)

A Python-based paper-trading bot that trains on one year of Alpaca historical data, generates aggressive long/short signals, and logs activity to a local desktop dashboard database (Tkinter).

**Disclaimer:** This project is for educational purposes only and is not financial advice.

## Quick Start

1. Create a virtual environment and install deps:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.bot.txt
```

2. Copy environment variables:

```bash
python3 scripts/setup_env.py
```

3. Update `data/sp500.csv` with the full S&P 500 list when ready.

## Commands

Train the model on one year of data:

```bash
python3 -m broker_bot.cli train
```

Run a backtest (in-sample, for quick feedback):

```bash
python3 -m broker_bot.cli backtest
```

Rebalance the paper portfolio using the latest signals:

```bash
python3 -m broker_bot.cli rebalance
```

Snapshot account + positions (no trades):

```bash
python3 -m broker_bot.cli snapshot
```

Launch the desktop dashboard (Tkinter):

```bash
python3 -m broker_bot.cli dashboard
```

Launch the local web dashboard (recommended for macOS Tk issues). The equity chart overlays SPY for comparison and shows 20D alpha/tracking error:

```bash
python3 -m broker_bot.cli dashboard-web
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser. If `API_TOKEN` is set, open with:
`http://127.0.0.1:8000/?token=YOUR_TOKEN`

You can override the host/port with env vars:

```bash
DASHBOARD_HOST=0.0.0.0 DASHBOARD_PORT=8000 python3 -m broker_bot.cli dashboard-web
```

### Streamlit (GitHub + Community Cloud)

You can deploy the UI via Streamlit Community Cloud using `streamlit_app.py`. The Streamlit app uses `requirements.txt` (minimal).

1. Push the repo to GitHub.
2. In Streamlit Community Cloud, select:
   - **Repository**: your repo
   - **Branch**: `main`
   - **Main file**: `streamlit_app.py`
3. Add the following **Secrets** (not in the repo):
   - If using the API approach: `API_BASE_URL` and `API_TOKEN`
   - If using GitHub snapshots (no API): `DATA_URL` pointing to the raw JSON, for example:
     `https://raw.githubusercontent.com/<user>/<repo>/main/data/dashboard_snapshot.json`

The Streamlit app calls your bot API endpoints and shows:
Equity vs SPY, positions, trades, and Advisor reports.

### GitHub Actions (Advisor + Snapshot Only)

This workflow runs daily (weekdays) and commits `data/dashboard_snapshot.json` so Streamlit can read it.

Workflow file: `.github/workflows/advisor_snapshot.yml`

**Secrets to add in GitHub**:
- `ALPACA_API_KEY`
- `ALPACA_SECRET_KEY`
- `ALPACA_PAPER_URL` (optional, defaults to paper endpoint)
- `ALPACA_DATA_FEED` (optional)
- `OPENAI_API_KEY` (if `LLM_ENABLED=1`)
- `LLM_ENABLED` (`1` to enable LLM advisor)
- `LLM_MODEL` (e.g. `gpt-5-mini`)

**Schedule note**: The cron is set for **21:15 UTC** (4:15pm ET in winter). During daylight saving time it will run at 5:15pm ET unless you update the schedule.

Generate a daily Advisor report (auto-applies small parameter tweaks by default):

```bash
python3 -m broker_bot.cli advisor-report
```

### LLM Advisor (Dynamic Policy Tweaks + Explainability)

The Advisor can optionally call an LLM to provide explainability and propose small, bounded parameter tweaks.

Set these in `.env` (or use secrets in CI):

```bash
OPENAI_API_KEY=your_key_here
LLM_ENABLED=1
LLM_MODEL=gpt-5-mini
```

LLM outputs are sanitized and clamped to conservative bounds before applying overrides.

## Notes

- The bot uses long/short signals with inverse-volatility sizing and an SPY regime filter (reduces leverage in bear regimes).
- The model is a Random Forest regressor on momentum/volatility features with market context.
- The backtest uses walk-forward retraining, weekly rebalancing, and transaction cost estimates for realism.
- Advisor overrides are stored in `data/advisor_overrides.json` and applied at startup when enabled.
- Optional sector exposure critiques use `data/sector_map.csv` (set via `SECTOR_MAP_PATH`).

### Risk & Liquidity Controls

- `MIN_PRICE` and `MIN_DOLLAR_VOL` filter illiquid or low-priced symbols.
- `VOL_TARGET` + `VOL_WINDOW` scales leverage down in high-volatility regimes.
- `MAX_DRAWDOWN`, `MIN_LEVERAGE`, and `DRAWDOWN_WINDOW` apply drawdown guardrails.
- Backtest-only reliability simulation:
  - `MISS_REBALANCE_PROB` simulates skipped rebalances (e.g., CI delays/failures).
  - `REBALANCE_DELAY_DAYS` delays a missed rebalance by N days.

### Reliability Impact Estimator

Compare baseline performance vs missed-rebalance scenarios:

```bash
python3 scripts/compare_reliability.py --miss-prob 0.05 --delay-days 1 --seeds 1 2 3 4 5
```
