from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import mean, stdev
import sqlite3
import csv

import pandas as pd

from .config import Config
from .data import fetch_daily_bars
from .features import build_features


@dataclass
class AdvisorReport:
    ts: str
    headline: str
    summary: str
    suggestions: list[str]
    metrics: dict[str, float]
    overrides: dict[str, float]


ALLOWED_OVERRIDES = {
    "min_long_return": {"min": 0.0001, "max": 0.01, "max_delta": 0.001, "type": float},
    "max_short_return": {"min": -0.01, "max": -0.0001, "max_delta": 0.001, "type": float},
    "gross_leverage": {"min": 0.3, "max": 3.0, "max_delta": 0.3, "type": float},
    "bear_leverage": {"min": 0.1, "max": 2.0, "max_delta": 0.3, "type": float},
    "max_position_pct": {"min": 0.01, "max": 0.2, "max_delta": 0.03, "type": float},
    "rebalance_top_k": {"min": 5, "max": 120, "max_delta": 15, "type": int},
    "tcost_bps": {"min": 1, "max": 50, "max_delta": 10, "type": float},
    "min_price": {"min": 1, "max": 20, "max_delta": 2, "type": float},
    "min_dollar_vol": {"min": 1_000_000, "max": 50_000_000, "max_delta": 2_000_000, "type": float},
    "vol_target": {"min": 0.005, "max": 0.05, "max_delta": 0.01, "type": float},
    "max_drawdown": {"min": 0.05, "max": 0.3, "max_delta": 0.05, "type": float},
    "min_leverage": {"min": 0.05, "max": 1.0, "max_delta": 0.2, "type": float},
}


def _read_equity_rows(db_path: str, limit: int = 200) -> list[tuple[str, float, float, float, float | None]]:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "SELECT ts, equity, cash, portfolio_value, spy_value FROM equity ORDER BY ts DESC LIMIT ?",
            (limit,),
        )
        return cursor.fetchall()


def _read_trade_rows(db_path: str, limit: int = 400) -> list[tuple[str, str, str, float, float | None, str | None]]:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "SELECT ts, symbol, side, qty, price, status FROM trades ORDER BY ts DESC LIMIT ?",
            (limit,),
        )
        return cursor.fetchall()


def _read_latest_positions(db_path: str) -> list[tuple[str, float, float | None]]:
    with sqlite3.connect(db_path) as conn:
        latest = conn.execute("SELECT ts FROM positions ORDER BY ts DESC LIMIT 1").fetchone()
        if not latest:
            return []
        ts = latest[0]
        rows = conn.execute(
            "SELECT symbol, qty, market_value FROM positions WHERE ts = ?",
            (ts,),
        ).fetchall()
        return rows


def _compute_drawdown(values: list[float]) -> float:
    peak = values[0]
    max_dd = 0.0
    for v in values[1:]:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _pct_change(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return (a / b) - 1.0


def _safe_mean(values: list[float]) -> float:
    return float(mean(values)) if values else 0.0


def _load_sector_map(path: str) -> dict[str, str]:
    sector_map: dict[str, str] = {}
    if not path or not Path(path).exists():
        return sector_map
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = (row.get("symbol") or row.get("Symbol") or "").strip().upper()
            sector = (row.get("sector") or row.get("Sector") or "").strip()
            if symbol and sector:
                sector_map[symbol] = sector
    return sector_map


def _compute_tracking_error(bot_returns: list[float], spy_returns: list[float]) -> float:
    diffs = [b - s for b, s in zip(bot_returns, spy_returns)]
    if len(diffs) < 2:
        return 0.0
    return float(stdev(diffs))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _current_config_map(config: Config) -> dict[str, float]:
    return {
        "min_long_return": config.min_long_return,
        "max_short_return": config.max_short_return,
        "gross_leverage": config.gross_leverage,
        "bear_leverage": config.bear_leverage,
        "max_position_pct": config.max_position_pct,
        "rebalance_top_k": float(config.rebalance_top_k),
        "tcost_bps": config.tcost_bps,
        "min_price": config.min_price,
        "min_dollar_vol": config.min_dollar_vol,
        "vol_target": config.vol_target,
        "max_drawdown": config.max_drawdown,
        "min_leverage": config.min_leverage,
    }


def _sanitize_overrides(config: Config, raw_overrides: dict[str, float]) -> dict[str, float]:
    clean: dict[str, float] = {}
    current = _current_config_map(config)
    for key, value in raw_overrides.items():
        if key not in ALLOWED_OVERRIDES:
            continue
        rule = ALLOWED_OVERRIDES[key]
        try:
            val = float(value)
        except Exception:
            continue
        base = current.get(key, val)
        max_delta = rule.get("max_delta")
        if max_delta is not None:
            val = _clamp(val, base - max_delta, base + max_delta)
        val = _clamp(val, rule["min"], rule["max"])
        if rule["type"] is int:
            val = float(int(round(val)))
        clean[key] = val
    return clean


def _call_llm(config: Config, context: dict) -> dict | None:
    if not os.getenv("OPENAI_API_KEY"):
        return None
    if not os.getenv("LLM_ENABLED", "0").strip().lower() in {"1", "true", "yes", "y"}:
        return None
    model = os.getenv("LLM_MODEL", "gpt-5-mini")
    try:
        from openai import OpenAI
    except Exception:
        return None

    client = OpenAI()
    system = (
        "You are a conservative policy advisor for a paper-trading bot. "
        "Return ONLY valid JSON with keys: summary (string), suggestions (array of strings), "
        "overrides (object of numeric values). "
        "Only override parameters from this allowlist: "
        + ", ".join(ALLOWED_OVERRIDES.keys())
        + ". Keep tweaks small and explainable."
    )
    user = json.dumps(context)
    request_kwargs = {
        "model": model,
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_output_tokens": 500,
    }
    # GPT-5 models in the Responses API do not accept temperature.
    if not model.lower().startswith("gpt-5"):
        request_kwargs["temperature"] = 0.2

    try:
        response = client.responses.create(**request_kwargs)
    except Exception as exc:
        message = str(exc).lower()
        if "temperature" in message and "unsupported" in message and "temperature" in request_kwargs:
            request_kwargs.pop("temperature", None)
            try:
                response = client.responses.create(**request_kwargs)
            except Exception:
                return None
        else:
            return None
    text = response.output_text or ""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start : end + 1])
    except Exception:
        return None


def generate_advisor_report(config: Config) -> AdvisorReport:
    rows = list(reversed(_read_equity_rows(config.db_path, limit=200)))
    if len(rows) < 5:
        ts = datetime.now(timezone.utc).isoformat()
        return AdvisorReport(
            ts=ts,
            headline="Not enough data",
            summary="Need more equity snapshots before generating a meaningful report.",
            suggestions=["Run daily snapshots and rebalances to build history."],
            metrics={},
            overrides={},
        )

    equities = [r[1] for r in rows]
    spy_values = [r[4] for r in rows]
    daily_returns = [
        _pct_change(equities[i], equities[i - 1])
        for i in range(1, len(equities))
        if equities[i - 1] != 0
    ]

    last_5 = equities[-6:] if len(equities) >= 6 else equities
    last_20 = equities[-21:] if len(equities) >= 21 else equities

    ret_5 = _pct_change(last_5[-1], last_5[0]) if len(last_5) > 1 else 0.0
    ret_20 = _pct_change(last_20[-1], last_20[0]) if len(last_20) > 1 else 0.0

    spy_ret_20 = 0.0
    if spy_values[0] is not None and spy_values[-1] is not None:
        valid_spy = [v for v in spy_values if v is not None]
        if len(valid_spy) > 1:
            spy_ret_20 = _pct_change(valid_spy[-1], valid_spy[0])

    drawdown = _compute_drawdown(equities)
    vol = _safe_mean([abs(r) for r in daily_returns])

    # Simple trade activity metric
    trades = _read_trade_rows(config.db_path, limit=400)
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    recent_trades = []
    for t in trades:
        try:
            ts = datetime.fromisoformat(t[0])
        except Exception:
            continue
        if ts >= cutoff:
            recent_trades.append(t)
    trade_count = len(recent_trades)

    metrics = {
        "ret_5d": ret_5,
        "ret_20d": ret_20,
        "spy_ret_20d": spy_ret_20,
        "drawdown": drawdown,
        "avg_abs_daily_return": vol,
        "trade_count_24h": float(trade_count),
    }

    suggestions: list[str] = []
    overrides: dict[str, float] = {}

    # Alpha & tracking error (20D)
    aligned = [(r[1], r[4]) for r in rows if r[4] is not None]
    alpha_20 = 0.0
    tracking_error = 0.0
    if len(aligned) >= 21:
        window = aligned[-21:]
        bot_ret_20 = _pct_change(window[-1][0], window[0][0])
        spy_ret_20_calc = _pct_change(window[-1][1], window[0][1]) if window[0][1] else 0.0
        alpha_20 = bot_ret_20 - spy_ret_20_calc
        bot_daily = [_pct_change(window[i][0], window[i - 1][0]) for i in range(1, len(window))]
        spy_daily = [_pct_change(window[i][1], window[i - 1][1]) for i in range(1, len(window))]
        tracking_error = _compute_tracking_error(bot_daily, spy_daily)
        metrics["alpha_20d"] = alpha_20
        metrics["tracking_error_20d"] = tracking_error

    # Trade diagnostics
    rejected = [t for t in recent_trades if t[5] and ("skipped" in t[5] or "rejected" in t[5])]
    reject_rate = (len(rejected) / trade_count) if trade_count else 0.0
    metrics["reject_rate"] = reject_rate

    notional = 0.0
    for _, _, _, qty, price, _ in recent_trades:
        if price is None:
            continue
        notional += abs(qty * price)
    metrics["notional_24h"] = notional

    # Factor & sector analysis from latest positions
    positions = _read_latest_positions(config.db_path)
    factor_summary = ""
    if positions:
        symbols = [p[0] for p in positions]
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=140)
        try:
            bars = fetch_daily_bars(config, symbols + ["SPY"], start, end).bars
            features = build_features(bars)
            latest_ts = pd.to_datetime(features["timestamp"]).max()
            latest = features[pd.to_datetime(features["timestamp"]) == latest_ts].copy()
            latest = latest.set_index("Symbol")

            # Compute weights by market value
            total_abs = 0.0
            weights: dict[str, float] = {}
            for symbol, qty, mkt in positions:
                notional_val = abs(mkt) if mkt is not None else abs(qty)
                if notional_val <= 0:
                    continue
                total_abs += notional_val
                sign = 1.0 if qty >= 0 else -1.0
                weights[symbol] = sign * notional_val
            if total_abs > 0:
                for symbol in weights:
                    weights[symbol] /= total_abs

            # Factor tilts
            mom = 0.0
            vol_tilt = 0.0
            rank = 0.0
            for symbol, w in weights.items():
                if symbol not in latest.index:
                    continue
                row = latest.loc[symbol]
                mom += w * float(row["mom_20d"])
                rank += w * float(row["rank_mom_20d"])
                vol_tilt += abs(w) * float(row["vol_20d"])

            spy_row = latest.loc["SPY"] if "SPY" in latest.index else None
            spy_mom = float(spy_row["mom_20d"]) if spy_row is not None else 0.0
            spy_vol = float(spy_row["vol_20d"]) if spy_row is not None else 0.0

            metrics["factor_mom_20d"] = mom
            metrics["factor_rank_mom"] = rank
            metrics["factor_vol_20d"] = vol_tilt
            metrics["spy_mom_20d"] = spy_mom
            metrics["spy_vol_20d"] = spy_vol

            if mom < 0 and spy_mom > 0:
                suggestions.append("Portfolio momentum tilt is negative vs SPY. Tighten long filters.")
                overrides["min_long_return"] = min(config.min_long_return + 0.0005, 0.005)
            if spy_vol > 0 and vol_tilt > spy_vol * 1.3:
                suggestions.append("Portfolio volatility is elevated vs SPY. Reduce leverage or position size.")
                overrides["gross_leverage"] = max(config.gross_leverage * 0.9, 0.5)
                overrides["max_position_pct"] = max(config.max_position_pct * 0.9, 0.02)

            # Beta estimate (weighted)
            prices = bars.pivot_table(index="timestamp", columns="Symbol", values="close").sort_index()
            returns = prices.pct_change().dropna()
            if "SPY" in returns.columns and len(returns) > 10:
                spy_ret = returns["SPY"]
                spy_var = spy_ret.var()
                beta = 0.0
                if spy_var > 0:
                    for symbol, w in weights.items():
                        if symbol not in returns.columns:
                            continue
                        cov = returns[symbol].cov(spy_ret)
                        beta += w * (cov / spy_var)
                metrics["beta"] = beta
                if beta > 1.2:
                    suggestions.append("Market beta is high. Reduce gross leverage in volatile regimes.")
                    overrides["gross_leverage"] = max(config.gross_leverage * 0.9, 0.5)

            # Sector concentration
            sector_map = _load_sector_map(config.sector_map_path)
            if sector_map:
                sector_weights: dict[str, float] = {}
                for symbol, w in weights.items():
                    sector = sector_map.get(symbol)
                    if not sector:
                        continue
                    sector_weights[sector] = sector_weights.get(sector, 0.0) + abs(w)
                if sector_weights:
                    max_sector = max(sector_weights, key=sector_weights.get)
                    max_weight = sector_weights[max_sector]
                    metrics["max_sector_weight"] = max_weight
                    factor_summary = f"Top sector: {max_sector} ({max_weight:.0%})."
                    if max_weight > 0.35:
                        suggestions.append("Sector concentration is high. Add a sector cap or reduce max position size.")
                        overrides["max_position_pct"] = max(config.max_position_pct * 0.9, 0.02)
            else:
                suggestions.append("Add sector_map.csv to enable sector exposure critiques.")

        except Exception:
            suggestions.append("Advisor factor analysis skipped due to missing data.")

    if ret_20 < spy_ret_20 - 0.01:
        suggestions.append("Underperforming SPY: tighten entry thresholds and reduce leverage.")
        overrides["min_long_return"] = min(config.min_long_return + 0.0005, 0.005)
        overrides["max_short_return"] = max(config.max_short_return - 0.0005, -0.005)
        overrides["gross_leverage"] = max(config.gross_leverage * 0.9, 0.6)
    elif ret_20 > spy_ret_20 + 0.02 and drawdown < 0.08:
        suggestions.append("Outperforming with low drawdown: modestly increase leverage.")
        overrides["gross_leverage"] = min(config.gross_leverage * 1.05, 2.0)

    if drawdown > 0.12:
        suggestions.append("Drawdown is elevated: reduce leverage and consider fewer positions.")
        overrides["gross_leverage"] = max(config.gross_leverage * 0.85, 0.5)
        overrides["rebalance_top_k"] = max(int(config.rebalance_top_k * 0.8), 10)

    if trade_count < 5:
        suggestions.append("Low trade activity: relax thresholds to generate more signals.")
        overrides["min_long_return"] = max(config.min_long_return - 0.0005, 0.0002)
        overrides["max_short_return"] = min(config.max_short_return + 0.0005, -0.0002)
    if trade_count == 0:
        suggestions.append("No trades in the last 24h. Verify the bot ran and market data is flowing.")

    if reject_rate > 0.2:
        suggestions.append("High rejection rate: cancel open orders or reduce order sizes.")

    if not suggestions:
        suggestions.append("No major issues detected. Keep collecting data and review weekly.")

    headline = "Advisor Update"
    summary_parts = [
        f"5D return {ret_5:.2%}",
        f"20D return {ret_20:.2%}",
        f"SPY 20D {spy_ret_20:.2%}",
        f"drawdown {drawdown:.2%}",
    ]
    if alpha_20:
        summary_parts.append(f"alpha 20D {alpha_20:.2%}")
    if tracking_error:
        summary_parts.append(f"tracking error {tracking_error:.2%}")
    if factor_summary:
        summary_parts.append(factor_summary)
    summary = ", ".join(summary_parts) + "."

    # LLM advisor (optional)
    llm_context = {
        "metrics": metrics,
        "current_params": _current_config_map(config),
        "notes": {
            "paper_trading": True,
            "objective": "Beat SPY with controlled drawdown",
        },
    }
    llm_resp = _call_llm(config, llm_context)
    if llm_resp:
        llm_summary = llm_resp.get("summary")
        llm_suggestions = llm_resp.get("suggestions") or []
        llm_overrides_raw = llm_resp.get("overrides") or {}

        if isinstance(llm_summary, str) and llm_summary.strip():
            suggestions.append(f"LLM: {llm_summary.strip()}")
        if isinstance(llm_suggestions, list):
            for s in llm_suggestions:
                if isinstance(s, str) and s.strip():
                    suggestions.append(f"LLM: {s.strip()}")

        if isinstance(llm_overrides_raw, dict):
            llm_overrides = _sanitize_overrides(config, llm_overrides_raw)
            if llm_overrides:
                overrides.update(llm_overrides)
                metrics["llm_used"] = 1.0
                metrics["llm_override_count"] = float(len(llm_overrides))

    ts = datetime.now(timezone.utc).isoformat()
    return AdvisorReport(
        ts=ts,
        headline=headline,
        summary=summary,
        suggestions=suggestions,
        metrics=metrics,
        overrides=overrides,
    )


def save_overrides(path: str, overrides: dict[str, float]) -> None:
    if not overrides:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(overrides, handle, indent=2, sort_keys=True)
