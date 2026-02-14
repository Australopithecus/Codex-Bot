from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pandas as pd

from .config import Config
from .data import fetch_daily_bars
from .features import build_features
from .model import train_model, save_model
from .backtest import run_backtest


def train_on_history(config: Config, symbols: list[str]) -> tuple[str, float]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=config.training_lookback_days)
    bars = fetch_daily_bars(config, symbols + ["SPY"], start, end).bars

    features = build_features(bars)
    features = features[features["Symbol"] != "SPY"].copy()
    if config.min_price > 0:
        features = features[features["close"] >= config.min_price]
    if config.min_dollar_vol > 0 and "dollar_vol_20d" in features.columns:
        features = features[features["dollar_vol_20d"] >= config.min_dollar_vol]
    if features.empty:
        raise RuntimeError("Not enough history to train the model.")

    model, metrics = train_model(features, horizon_days=config.prediction_horizon_days)
    model_path = save_model(model, config.model_dir)
    return model_path, metrics


def run_backtest_on_history(config: Config, symbols: list[str]) -> pd.DataFrame:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=config.training_lookback_days)
    bars = fetch_daily_bars(config, symbols + ["SPY"], start, end).bars
    return run_backtest(
        bars,
        horizon_days=config.prediction_horizon_days,
        min_long_return=config.min_long_return,
        max_short_return=config.max_short_return,
        gross_leverage=config.gross_leverage,
        top_k=config.rebalance_top_k,
        max_position_pct=config.max_position_pct,
        rebalance_frequency=config.rebalance_frequency,
        tcost_bps=config.tcost_bps,
        bear_leverage=config.bear_leverage,
        lookback_days=config.training_lookback_days,
        min_price=config.min_price,
        min_dollar_vol=config.min_dollar_vol,
        vol_target=config.vol_target,
        vol_window=config.vol_window,
        max_drawdown=config.max_drawdown,
        min_leverage=config.min_leverage,
        miss_rebalance_prob=config.miss_rebalance_prob,
        rebalance_delay_days=config.rebalance_delay_days,
        sim_seed=config.sim_seed,
    )
