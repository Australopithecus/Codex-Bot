#!/usr/bin/env python3
from __future__ import annotations

import argparse
import statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from broker_bot.config import load_config
from broker_bot.data import fetch_daily_bars
from broker_bot.universe import load_universe
from broker_bot.backtest import run_backtest


def run_backtest_with_params(bars, config, miss_prob: float, delay_days: int, seed: int) -> float:
    result = run_backtest(
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
        miss_rebalance_prob=miss_prob,
        rebalance_delay_days=delay_days,
        sim_seed=seed,
    )
    if result.empty:
        return 1.0
    return float(result["strategy_equity"].iloc[-1])


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare baseline vs missed-rebalance backtests")
    parser.add_argument("--miss-prob", type=float, default=0.05, help="Probability of missing a rebalance (0-1)")
    parser.add_argument("--delay-days", type=int, default=1, help="Days to delay a missed rebalance")
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5], help="Random seeds")
    args = parser.parse_args()

    config = load_config()
    symbols = load_universe(config.universe_path)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=config.training_lookback_days)
    bars = fetch_daily_bars(config, symbols + ["SPY"], start, end).bars

    print("Running baseline (no misses)...")
    baseline = run_backtest_with_params(bars, config, miss_prob=0.0, delay_days=0, seed=args.seeds[0])

    print(f"Running scenario: miss_prob={args.miss_prob}, delay_days={args.delay_days}...")
    scenario_results = []
    for seed in args.seeds:
        eq = run_backtest_with_params(bars, config, miss_prob=args.miss_prob, delay_days=args.delay_days, seed=seed)
        scenario_results.append(eq)

    avg = statistics.mean(scenario_results)
    std = statistics.pstdev(scenario_results) if len(scenario_results) > 1 else 0.0
    impact = (avg / baseline) - 1.0 if baseline else 0.0

    print("\nResults")
    print(f"Baseline final equity: {baseline:.4f}x")
    print(f"Scenario avg equity:   {avg:.4f}x (std: {std:.4f})")
    print(f"Estimated impact:      {impact * 100:.2f}% vs baseline")


if __name__ == "__main__":
    main()
