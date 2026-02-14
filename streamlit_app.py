import os
import json
import requests
import streamlit as st

API_BASE = os.getenv("API_BASE_URL", "")
API_TOKEN = os.getenv("API_TOKEN", "")
DATA_URL = os.getenv("DATA_URL", "")

st.set_page_config(page_title="Broker Bot Dashboard", layout="wide")

st.title("Broker Bot Dashboard")
st.caption("Streamlit UI (reads from the Broker Bot API)")

def fetch(path: str):
    if API_BASE:
        headers = {"X-API-Token": API_TOKEN} if API_TOKEN else {}
        url = API_BASE.rstrip("/") + path
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()
    if DATA_URL:
        resp = requests.get(DATA_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if path == "/api/summary":
            equity = data.get("equity", [])
            if not equity:
                return {"status": "empty", "message": "No equity snapshots yet."}
            latest = equity[-1]
            return {
                "status": "ok",
                "ts": latest["ts"],
                "equity": latest["equity"],
                "cash": latest.get("cash", 0.0),
                "portfolio": latest.get("portfolio_value", 0.0),
                "spy": latest.get("spy_value"),
            }
        if path == "/api/equity":
            return {"data": data.get("equity", [])}
        if path == "/api/positions":
            return {"data": data.get("positions", [])}
        if path == "/api/trades":
            return {"data": data.get("trades", [])}
        if path == "/api/advisor":
            return {"data": data.get("advisor_reports", [])}
        return {}
    st.error("Set API_BASE_URL or DATA_URL in Streamlit secrets.")
    st.stop()


try:
    summary = fetch("/api/summary")
except Exception as exc:
    st.error(f"Failed to load summary: {exc}")
    st.stop()

if summary.get("status") != "ok":
    st.warning(summary.get("message", "No data"))
    st.stop()

col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Equity", f"${summary['equity']:,.2f}")
col2.metric("Cash", f"${summary['cash']:,.2f}")
col3.metric("Portfolio", f"${summary['portfolio']:,.2f}")
col4.metric("SPY", f"${summary['spy']:,.2f}" if summary.get("spy") else "--")
col5.metric("Alpha 20D", "--")
col6.metric("Tracking Error", "--")


equity = fetch("/api/equity").get("data", [])
if equity:
    import pandas as pd
    df = pd.DataFrame(equity)
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.set_index("ts")
    st.subheader("Equity vs SPY")
    if "spy" in df.columns and df["spy"].notna().sum() > 1:
        base_equity = df["equity"].iloc[0]
        spy_norm = (df["spy"] / df["spy"].iloc[0]) * base_equity
        chart_df = df[["equity"]].copy()
        chart_df["spy"] = spy_norm
        st.line_chart(chart_df)

        # Alpha and tracking error (20D)
        window = chart_df.dropna().tail(21)
        if len(window) >= 21:
            bot_ret = window["equity"].iloc[-1] / window["equity"].iloc[0] - 1
            spy_ret = window["spy"].iloc[-1] / window["spy"].iloc[0] - 1
            alpha = bot_ret - spy_ret
            diffs = window["equity"].pct_change().dropna() - window["spy"].pct_change().dropna()
            tracking_error = diffs.std()
            col5.metric("Alpha 20D", f"{alpha * 100:.2f}%")
            col6.metric("Tracking Error", f"{tracking_error * 100:.2f}%")
    else:
        st.line_chart(df[["equity"]])

positions = fetch("/api/positions").get("data", [])
trades = fetch("/api/trades").get("data", [])
advisor = fetch("/api/advisor").get("data", [])

st.subheader("Positions")
if positions:
    st.dataframe(positions, use_container_width=True)

    try:
        import pandas as pd
        pos_df = pd.DataFrame(positions)
        if "market_value" in pos_df.columns:
            pos_df["market_value"] = pd.to_numeric(pos_df["market_value"], errors="coerce").fillna(0.0)
            pos_df = pos_df[pos_df["market_value"] != 0]
            if not pos_df.empty:
                pos_df["abs_value"] = pos_df["market_value"].abs()
                pos_df["side"] = pos_df["market_value"].apply(lambda v: "Short" if v < 0 else "Long")
                chart_df = pos_df.set_index("symbol")["abs_value"]
                st.subheader("Holdings Allocation")
                st.caption("Ring chart based on absolute market value. Shorts are slightly separated.")

                # Add cash as a slice if available
                cash_value = summary.get("cash")
                chart_labels = chart_df.index.tolist()
                chart_values = chart_df.values.tolist()
                chart_pulls = [0.08 if s == "Short" else 0.0 for s in pos_df["side"]]

                if cash_value is not None:
                    chart_labels.append("CASH")
                    chart_values.append(abs(float(cash_value)))
                    chart_pulls.append(0.0)

                long_count = int((pos_df["side"] == "Long").sum())
                short_count = int((pos_df["side"] == "Short").sum())
                st.caption(f"Legend counts — Long: {long_count} | Short: {short_count}")

                st.plotly_chart(
                    {
                        "data": [
                            {
                                "labels": chart_labels,
                                "values": chart_values,
                                "type": "pie",
                                "hole": 0.5,
                                "pull": chart_pulls,
                                "hovertemplate": "%{label}<br>$%{value:,.2f}<br>%{percent}<extra></extra>",
                            }
                        ],
                        "layout": {"showlegend": True},
                    },
                    use_container_width=True,
                )
    except Exception:
        pass
else:
    st.caption("No positions logged yet.")

st.subheader("Recent Trades")
if trades:
    st.dataframe(trades, use_container_width=True)
else:
    st.caption("No trades logged yet.")

st.subheader("Advisor Reports")
if advisor:
    for report in advisor[:5]:
        st.markdown(f"**{report.get('headline','Advisor Report')}** — {report.get('ts','')}")
        st.write(report.get("summary", ""))
        suggestions = report.get("suggestions", [])
        if suggestions:
            st.markdown("**Suggestions**")
            for s in suggestions:
                st.markdown(f"- {s}")
        overrides = report.get("overrides", {})
        if overrides:
            st.caption("Overrides: " + ", ".join([f"{k}={v}" for k, v in overrides.items()]))
        st.divider()
else:
    st.caption("No advisor reports yet.")
