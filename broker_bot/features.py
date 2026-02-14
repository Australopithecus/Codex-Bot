from __future__ import annotations

import pandas as pd


FEATURE_COLUMNS = [
    "return_1d",
    "return_5d",
    "return_10d",
    "mom_20d",
    "vol_20d",
    "range_5d",
    "market_return_1d",
    "market_mom_20d",
    "rank_mom_20d",
]


def _attach_market_features(df: pd.DataFrame, market_symbol: str = "SPY") -> pd.DataFrame:
    market = df[df["Symbol"] == market_symbol].copy()
    if market.empty:
        raise RuntimeError(f"Market symbol {market_symbol} not found in bars. Include it in the universe.")
    market = market.sort_values("timestamp")
    market["market_return_1d"] = market["close"].pct_change(1)
    market["market_mom_20d"] = market["close"].pct_change(20)
    market = market[["timestamp", "market_return_1d", "market_mom_20d"]]
    return df.merge(market, on="timestamp", how="left")


def build_features(bars: pd.DataFrame, market_symbol: str = "SPY") -> pd.DataFrame:
    df = bars.copy()
    df = df.sort_values(["Symbol", "timestamp"]).reset_index(drop=True)

    df["close"] = df["close"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    if "volume" in df.columns:
        df["volume"] = df["volume"].astype(float)
    else:
        df["volume"] = 0.0

    grouped = df.groupby("Symbol", group_keys=False)
    df["return_1d"] = grouped["close"].pct_change(1)
    df["return_5d"] = grouped["close"].pct_change(5)
    df["return_10d"] = grouped["close"].pct_change(10)
    df["mom_20d"] = grouped["close"].pct_change(20)
    df["vol_20d"] = grouped["close"].pct_change().rolling(20).std().reset_index(level=0, drop=True)
    intraday_range = (df["high"] - df["low"]) / df["close"]
    df["range_5d"] = intraday_range.groupby(df["Symbol"]).rolling(5).mean().reset_index(level=0, drop=True)
    df["dollar_vol"] = df["close"] * df["volume"]
    df["dollar_vol_20d"] = (
        grouped["dollar_vol"].rolling(20).mean().reset_index(level=0, drop=True)
    )

    df = _attach_market_features(df, market_symbol=market_symbol)

    # Cross-sectional momentum rank per day (0-1), exclude market symbol to avoid bias.
    df["rank_mom_20d"] = 0.5
    mask = df["Symbol"] != market_symbol
    df.loc[mask, "rank_mom_20d"] = (
        df.loc[mask].groupby("timestamp")["mom_20d"].rank(pct=True)
    )

    df = df.dropna(subset=FEATURE_COLUMNS)
    return df


def build_labels(df: pd.DataFrame, horizon_days: int) -> pd.Series:
    grouped = df.groupby("Symbol", group_keys=False)
    future_return = grouped["close"].pct_change(periods=horizon_days).shift(-horizon_days)
    return future_return
