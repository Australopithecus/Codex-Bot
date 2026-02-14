from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta


import pandas as pd
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.common.exceptions import APIError

from .config import Config
from .data import fetch_daily_bars
from .features import build_features
from .model import load_model, predict_return
from .logging_db import read_latest_equity


@dataclass
class Signal:
    symbol: str
    score: float
    side: str  # LONG or SHORT or HOLD
    vol: float | None = None


def _latest_date(df: pd.DataFrame) -> datetime:
    return pd.to_datetime(df["timestamp"]).max().to_pydatetime()


def _regime_leverage(spy_df: pd.DataFrame, gross_leverage: float, bear_leverage: float) -> float:
    if spy_df.empty:
        return gross_leverage
    spy_df = spy_df.sort_values("timestamp")
    closes = spy_df["close"]
    if len(closes) < 200:
        return gross_leverage
    ma50 = closes.rolling(50).mean().iloc[-1]
    ma200 = closes.rolling(200).mean().iloc[-1]
    if ma50 < ma200:
        return bear_leverage
    return gross_leverage


def _compute_drawdown(values: list[float]) -> float:
    if not values:
        return 0.0
    peak = values[0]
    max_dd = 0.0
    for v in values[1:]:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _spy_volatility(spy_df: pd.DataFrame, window: int) -> float:
    if spy_df.empty or window <= 1:
        return 0.0
    spy_df = spy_df.sort_values("timestamp")
    returns = spy_df["close"].pct_change().dropna()
    if len(returns) < window:
        return 0.0
    return float(returns.rolling(window).std().iloc[-1])


def _asset_info(trading: TradingClient, symbol: str, cache: dict[str, dict[str, bool]]) -> dict[str, bool]:
    if symbol in cache:
        return cache[symbol]
    asset = trading.get_asset(symbol)
    info = {
        "shortable": bool(getattr(asset, "shortable", False)),
        "tradable": bool(getattr(asset, "tradable", True)),
    }
    cache[symbol] = info
    return info


def _is_shortable(trading: TradingClient, symbol: str, cache: dict[str, dict[str, bool]]) -> bool:
    info = _asset_info(trading, symbol, cache)
    return info["shortable"] and info["tradable"]


def _is_tradable(trading: TradingClient, symbol: str, cache: dict[str, dict[str, bool]]) -> bool:
    info = _asset_info(trading, symbol, cache)
    return info["tradable"]


def generate_signals(config: Config, symbols: list[str]) -> tuple[pd.DataFrame, list[Signal], float, float]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=260)
    bars = fetch_daily_bars(config, symbols + ["SPY"], start, end).bars

    features = build_features(bars)
    if features.empty:
        raise RuntimeError("Not enough data to build features for signals.")

    latest_ts = _latest_date(features)
    latest = features[pd.to_datetime(features["timestamp"]) == latest_ts].copy()
    latest = latest[latest["Symbol"] != "SPY"].copy()

    model = load_model(config.model_dir)
    preds = predict_return(model, latest)
    latest["pred_return"] = preds.values

    if config.min_price > 0:
        latest = latest[latest["close"] >= config.min_price]
    if config.min_dollar_vol > 0 and "dollar_vol_20d" in latest.columns:
        latest = latest[latest["dollar_vol_20d"] >= config.min_dollar_vol]

    long_candidates = latest[latest["pred_return"] >= config.min_long_return].sort_values("pred_return", ascending=False)
    short_candidates = latest[latest["pred_return"] <= config.max_short_return].sort_values("pred_return", ascending=True)

    longs = long_candidates.head(config.rebalance_top_k)
    shorts = short_candidates.head(config.rebalance_top_k)

    signals: list[Signal] = []
    for _, row in longs.iterrows():
        signals.append(Signal(symbol=row["Symbol"], score=float(row["pred_return"]), side="LONG", vol=float(row["vol_20d"])))
    for _, row in shorts.iterrows():
        signals.append(Signal(symbol=row["Symbol"], score=float(row["pred_return"]), side="SHORT", vol=float(row["vol_20d"])))

    for _, row in latest.iterrows():
        if row["Symbol"] not in {s.symbol for s in signals}:
            signals.append(Signal(symbol=row["Symbol"], score=float(row["pred_return"]), side="HOLD", vol=float(row["vol_20d"])))

    spy_df = bars[bars["Symbol"] == "SPY"]
    regime_lev = _regime_leverage(spy_df, config.gross_leverage, config.bear_leverage)
    spy_vol = _spy_volatility(spy_df, config.vol_window)
    return latest, signals, regime_lev, spy_vol


def _target_weights(
    signals: list[Signal], gross_leverage: float, max_position_pct: float, top_k: int, allow_shorts: bool
) -> dict[str, float]:
    longs = [s for s in signals if s.side == "LONG"][:top_k]
    shorts = [s for s in signals if s.side == "SHORT"][:top_k] if allow_shorts else []

    weights: dict[str, float] = {}
    if not longs and not shorts:
        return weights

    if allow_shorts:
        long_gross = gross_leverage / 2.0
        short_gross = gross_leverage / 2.0
    else:
        long_gross = gross_leverage
        short_gross = 0.0

    if longs:
        inv_vol = [(1.0 / max(s.vol or 1e-6, 1e-6)) for s in longs]
        total = sum(inv_vol)
        for s, iv in zip(longs, inv_vol):
            weight = (iv / total) * long_gross
            weights[s.symbol] = min(max_position_pct, weight)
    if shorts:
        inv_vol = [(1.0 / max(s.vol or 1e-6, 1e-6)) for s in shorts]
        total = sum(inv_vol)
        for s, iv in zip(shorts, inv_vol):
            weight = (iv / total) * short_gross
            weights[s.symbol] = -min(max_position_pct, weight)

    return weights


def rebalance_portfolio(
    config: Config, symbols: list[str]
) -> tuple[str, list[tuple[str, str, float, float | None, str | None, str | None]], list[Signal]]:
    trading = TradingClient(config.alpaca_api_key, config.alpaca_secret_key, paper=True)
    latest, signals, regime_lev, spy_vol = generate_signals(config, symbols)

    account = trading.get_account()
    shorting_flag = getattr(account, "shorting_enabled", False)
    if isinstance(shorting_flag, str):
        shorting_enabled = shorting_flag.strip().lower() in {"true", "1", "yes", "y"}
    else:
        shorting_enabled = bool(shorting_flag)
    asset_cache: dict[str, dict[str, bool]] = {}

    # Vol targeting and drawdown guardrails
    leverage = regime_lev
    if config.vol_target > 0 and spy_vol > 0:
        vol_scale = min(1.0, config.vol_target / spy_vol)
        leverage *= vol_scale

    dd_rows = read_latest_equity(config.db_path, limit=config.drawdown_window)
    equities = [row[1] for row in reversed(dd_rows)]
    dd = _compute_drawdown(equities) if len(equities) > 1 else 0.0
    if config.max_drawdown > 0 and dd > config.max_drawdown:
        leverage *= max(config.max_drawdown / dd, 0.1)

    leverage = max(config.min_leverage, min(leverage, config.gross_leverage))

    weights = _target_weights(
        signals,
        leverage,
        config.max_position_pct,
        config.rebalance_top_k,
        allow_shorts=shorting_enabled,
    )

    # Enforce tradable/shortable filters
    filtered: dict[str, float] = {}
    for sym, w in weights.items():
        if w < 0 and not _is_shortable(trading, sym, asset_cache):
            continue
        if w > 0 and not _is_tradable(trading, sym, asset_cache):
            continue
        filtered[sym] = w
    weights = filtered

    equity = float(account.equity)

    # Map latest prices
    latest_prices = {row["Symbol"]: float(row["close"]) for _, row in latest.iterrows()}

    # Current positions
    current_positions = {p.symbol: float(p.qty) for p in trading.get_all_positions()}

    orders_to_log = []

    open_order_symbols = set()
    try:
        try:
            from alpaca.trading.enums import OrderStatus  # type: ignore
            request = GetOrdersRequest(status=OrderStatus.OPEN)
        except Exception:
            request = GetOrdersRequest(status="open")
        open_orders = trading.get_orders(request)
        open_order_symbols = {o.symbol for o in open_orders}
    except Exception:
        open_order_symbols = set()

    for symbol, target_weight in weights.items():
        if symbol not in latest_prices:
            continue
        if symbol in open_order_symbols:
            # Avoid submitting overlapping orders on the same symbol.
            continue
        target_value = equity * target_weight
        price = latest_prices[symbol]
        if price <= 0:
            continue
        target_qty = target_value / price
        if not shorting_enabled and target_qty < 0:
            target_qty = 0.0
        current_qty = current_positions.get(symbol, 0.0)
        delta_qty = target_qty - current_qty

        if abs(delta_qty) < 1e-3:
            continue

        side = OrderSide.BUY if delta_qty > 0 else OrderSide.SELL
        qty = abs(delta_qty)

        # Alpaca does not allow fractional short sells. If target is short, force whole shares.
        if target_qty < 0:
            qty = float(int(qty))
            if qty < 1:
                continue
        if not shorting_enabled and side == OrderSide.SELL:
            qty = min(qty, current_qty)
            if qty <= 0:
                continue

        order = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=side,
            time_in_force=TimeInForce.DAY,
        )
        try:
            submitted = trading.submit_order(order)
            orders_to_log.append((
                datetime.now(timezone.utc).isoformat(),
                symbol,
                side.value,
                float(qty),
                price,
                submitted.id,
                submitted.status,
            ))
        except APIError as exc:
            message = str(exc)
            if "40310000" in message or "insufficient qty available" in message:
                # If we attempted to short without borrow availability, fall back to closing only.
                if side == OrderSide.SELL and current_qty > 0:
                    close_qty = float(min(qty, current_qty))
                    if close_qty > 0:
                        close_order = MarketOrderRequest(
                            symbol=symbol,
                            qty=close_qty,
                            side=side,
                            time_in_force=TimeInForce.DAY,
                        )
                        try:
                            submitted = trading.submit_order(close_order)
                            orders_to_log.append((
                                datetime.now(timezone.utc).isoformat(),
                                symbol,
                                side.value,
                                float(close_qty),
                                price,
                                submitted.id,
                                submitted.status,
                            ))
                            continue
                        except APIError as exc2:
                            orders_to_log.append((
                                datetime.now(timezone.utc).isoformat(),
                                symbol,
                                side.value,
                                float(close_qty),
                                price,
                                None,
                                f"rejected: {exc2}",
                            ))
                            continue
                orders_to_log.append((
                    datetime.now(timezone.utc).isoformat(),
                    symbol,
                    side.value,
                    float(qty),
                    price,
                    None,
                    "skipped_insufficient_qty_or_open_order",
                ))
                continue
            raise

    # Close positions not in target weights
    for symbol, qty in current_positions.items():
        if symbol in weights:
            continue
        if abs(qty) < 1e-3:
            continue
        if symbol in open_order_symbols:
            continue
        side = OrderSide.SELL if qty > 0 else OrderSide.BUY
        order = MarketOrderRequest(
            symbol=symbol,
            qty=abs(qty),
            side=side,
            time_in_force=TimeInForce.DAY,
        )
        submitted = trading.submit_order(order)
        orders_to_log.append((
            datetime.now(timezone.utc).isoformat(),
            symbol,
            side.value,
            float(abs(qty)),
            latest_prices.get(symbol),
            submitted.id,
            submitted.status,
        ))

    return datetime.now(timezone.utc).isoformat(), orders_to_log, signals


def snapshot_positions(config: Config) -> tuple[str, list[tuple[str, float, float | None, float | None, float | None]]]:
    trading = TradingClient(config.alpaca_api_key, config.alpaca_secret_key, paper=True)
    positions = trading.get_all_positions()
    rows = []
    for p in positions:
        rows.append((p.symbol, float(p.qty), float(p.avg_entry_price), float(p.market_value), float(p.unrealized_pl)))
    return datetime.now(timezone.utc).isoformat(), rows


def snapshot_equity(config: Config) -> tuple[str, float, float, float]:
    trading = TradingClient(config.alpaca_api_key, config.alpaca_secret_key, paper=True)
    account = trading.get_account()
    ts = datetime.now(timezone.utc).isoformat()
    return ts, float(account.equity), float(account.cash), float(account.portfolio_value)
