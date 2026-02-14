from __future__ import annotations

import random
import pandas as pd

from .features import FEATURE_COLUMNS, build_features
from .model import train_model, predict_return


def _regime_leverage(market_df: pd.DataFrame, gross_leverage: float, bear_leverage: float) -> float:
    if market_df.empty:
        return gross_leverage
    closes = market_df.sort_values("timestamp")["close"]
    if len(closes) < 200:
        return gross_leverage
    ma50 = closes.rolling(50).mean().iloc[-1]
    ma200 = closes.rolling(200).mean().iloc[-1]
    if ma50 < ma200:
        return bear_leverage
    return gross_leverage


def _inverse_vol_weights(
    slice_df: pd.DataFrame,
    top_k: int,
    min_long_return: float,
    max_short_return: float,
    gross_leverage: float,
    max_position_pct: float,
    allow_shorts: bool,
) -> dict[str, float]:
    weights: dict[str, float] = {}
    if slice_df.empty:
        return weights

    longs = slice_df[slice_df["pred_return"] >= min_long_return].sort_values("pred_return", ascending=False).head(top_k)
    shorts = (
        slice_df[slice_df["pred_return"] <= max_short_return].sort_values("pred_return", ascending=True).head(top_k)
        if allow_shorts
        else slice_df.iloc[0:0]
    )

    if allow_shorts:
        long_gross = gross_leverage / 2.0
        short_gross = gross_leverage / 2.0
    else:
        long_gross = gross_leverage
        short_gross = 0.0

    if not longs.empty:
        inv_vol = 1.0 / longs["vol_20d"].clip(lower=1e-6)
        scaled = inv_vol / inv_vol.sum()
        for symbol, weight in zip(longs["Symbol"], scaled):
            weights[symbol] = min(max_position_pct, float(weight) * long_gross)

    if not shorts.empty:
        inv_vol = 1.0 / shorts["vol_20d"].clip(lower=1e-6)
        scaled = inv_vol / inv_vol.sum()
        for symbol, weight in zip(shorts["Symbol"], scaled):
            weights[symbol] = -min(max_position_pct, float(weight) * short_gross)

    return weights


def run_backtest(
    bars: pd.DataFrame,
    horizon_days: int,
    min_long_return: float,
    max_short_return: float,
    gross_leverage: float,
    top_k: int,
    max_position_pct: float,
    rebalance_frequency: str,
    tcost_bps: float,
    bear_leverage: float,
    lookback_days: int,
    min_price: float,
    min_dollar_vol: float,
    vol_target: float,
    vol_window: int,
    max_drawdown: float,
    min_leverage: float,
    miss_rebalance_prob: float,
    rebalance_delay_days: int,
    sim_seed: int,
) -> pd.DataFrame:
    features = build_features(bars)
    features = features[features["Symbol"] != "SPY"].copy()
    features["next_return"] = features.groupby("Symbol")["close"].pct_change(periods=horizon_days).shift(-horizon_days)

    dates = sorted(features["timestamp"].unique())
    if len(dates) < 60:
        raise RuntimeError("Not enough data to backtest.")

    # Determine rebalance dates (weekly by default)
    dates_df = pd.DataFrame({"timestamp": sorted(features["timestamp"].unique())})
    dates_df["timestamp"] = pd.to_datetime(dates_df["timestamp"])
    dates_df["rebalance_bucket"] = dates_df["timestamp"].dt.to_period(rebalance_frequency)
    rebalance_dates = set(dates_df.groupby("rebalance_bucket")["timestamp"].max().tolist())

    daily_returns = []
    current_weights: dict[str, float] = {}

    equity = 1.0
    equity_curve: list[float] = [equity]

    rng = random.Random(sim_seed)
    pending_rebalance_dt = None

    for ts in sorted(features["timestamp"].unique()):
        ts_dt = pd.to_datetime(ts)
        slice_df = features[features["timestamp"] == ts].copy()

        if min_price > 0:
            slice_df = slice_df[slice_df["close"] >= min_price]
        if min_dollar_vol > 0 and "dollar_vol_20d" in slice_df.columns:
            slice_df = slice_df[slice_df["dollar_vol_20d"] >= min_dollar_vol]
        slice_df = slice_df.dropna(subset=["next_return"])

        if slice_df.empty:
            # No eligible symbols today; hold weights and record flat return.
            daily_returns.append((ts_dt, 0.0))
            equity_curve.append(equity)
            continue

        should_rebalance = ts_dt in rebalance_dates
        if pending_rebalance_dt is not None and ts_dt >= pending_rebalance_dt:
            should_rebalance = True
            pending_rebalance_dt = None

        if should_rebalance:
            if miss_rebalance_prob > 0 and rng.random() < miss_rebalance_prob:
                if rebalance_delay_days > 0:
                    pending_rebalance_dt = ts_dt + pd.Timedelta(days=rebalance_delay_days)
                # Skip rebalancing but still compute daily returns with existing weights.
                should_rebalance = False

        if should_rebalance:
            market_df = bars[bars["Symbol"] == "SPY"]
            regime_lev = _regime_leverage(market_df[market_df["timestamp"] <= ts_dt], gross_leverage, bear_leverage)

            # Walk-forward retraining (rolling window)
            train_start = ts_dt - pd.Timedelta(days=lookback_days)
            train_df = features[
                (pd.to_datetime(features["timestamp"]) < ts_dt)
                & (pd.to_datetime(features["timestamp"]) >= train_start)
            ].copy()
            if min_price > 0:
                train_df = train_df[train_df["close"] >= min_price]
            if min_dollar_vol > 0 and "dollar_vol_20d" in train_df.columns:
                train_df = train_df[train_df["dollar_vol_20d"] >= min_dollar_vol]
            if len(train_df) > 0:
                model, _ = train_model(train_df, horizon_days=horizon_days)
                slice_df["pred_return"] = predict_return(model, slice_df)
            else:
                slice_df["pred_return"] = 0.0

            # Vol targeting on SPY
            spy_df = market_df[market_df["timestamp"] <= ts_dt].sort_values("timestamp")
            spy_returns = spy_df["close"].pct_change().dropna()
            if vol_target > 0 and len(spy_returns) >= vol_window:
                spy_vol = spy_returns.rolling(vol_window).std().iloc[-1]
                if spy_vol and spy_vol > 0:
                    regime_lev = min(regime_lev, regime_lev * min(1.0, vol_target / spy_vol))

            # Drawdown guardrail
            if max_drawdown > 0:
                peak = max(equity_curve) if equity_curve else equity
                dd = (peak - equity) / peak if peak > 0 else 0.0
                if dd > max_drawdown:
                    regime_lev *= max(max_drawdown / dd, 0.1)

            regime_lev = max(min_leverage, min(regime_lev, gross_leverage))

            new_weights = _inverse_vol_weights(
                slice_df,
                top_k=top_k,
                min_long_return=min_long_return,
                max_short_return=max_short_return,
                gross_leverage=regime_lev,
                max_position_pct=max_position_pct,
                allow_shorts=True,
            )
            turnover = sum(abs(new_weights.get(sym, 0.0) - current_weights.get(sym, 0.0)) for sym in set(new_weights) | set(current_weights))
            current_weights = new_weights
            cost = (tcost_bps / 10000.0) * turnover
        else:
            cost = 0.0

        if slice_df.empty:
            continue

        daily_ret = 0.0
        for _, row in slice_df.iterrows():
            weight = current_weights.get(row["Symbol"], 0.0)
            daily_ret += weight * float(row["next_return"])

        daily_ret -= cost
        daily_returns.append((ts_dt, daily_ret))
        equity = equity * (1 + daily_ret)
        equity_curve.append(equity)

    result = pd.DataFrame(daily_returns, columns=["timestamp", "strategy_return"]).sort_values("timestamp")
    result["strategy_equity"] = (1 + result["strategy_return"]).cumprod()
    return result
