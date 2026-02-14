import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Config:
    alpaca_api_key: str
    alpaca_secret_key: str
    alpaca_paper_url: str
    alpaca_data_feed: str
    universe_path: str
    db_path: str
    model_dir: str
    training_lookback_days: int
    prediction_horizon_days: int
    rebalance_top_k: int
    min_long_return: float
    max_short_return: float
    max_position_pct: float
    gross_leverage: float
    bear_leverage: float
    rebalance_frequency: str
    tcost_bps: float
    min_price: float
    min_dollar_vol: float
    vol_target: float
    vol_window: int
    max_drawdown: float
    min_leverage: float
    drawdown_window: int
    miss_rebalance_prob: float
    rebalance_delay_days: int
    sim_seed: int
    advisor_overrides_path: str
    advisor_auto_apply: bool
    sector_map_path: str


def load_config() -> Config:
    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    secret_key = os.getenv("ALPACA_SECRET_KEY", "").strip()
    paper_url = os.getenv("ALPACA_PAPER_URL", "https://paper-api.alpaca.markets").strip()
    data_feed = os.getenv("ALPACA_DATA_FEED", "iex").strip()
    overrides_path = os.getenv("ADVISOR_OVERRIDES_PATH", "data/advisor_overrides.json").strip()
    auto_apply_flag = os.getenv("ADVISOR_AUTO_APPLY", "1").strip().lower() in {"1", "true", "yes", "y"}
    sector_map_path = os.getenv("SECTOR_MAP_PATH", "data/sector_map.csv").strip()

    if not api_key or not secret_key:
        raise RuntimeError("Missing ALPACA_API_KEY or ALPACA_SECRET_KEY in environment.")

    # Optional advisor overrides
    overrides: dict[str, float] = {}
    if overrides_path and os.path.exists(overrides_path):
        try:
            import json
            with open(overrides_path, "r", encoding="utf-8") as handle:
                overrides = json.load(handle) or {}
        except Exception:
            overrides = {}

    def _override(name: str, default: float) -> float:
        try:
            return float(overrides.get(name, default))
        except Exception:
            return default

    def _override_int(name: str, default: int) -> int:
        try:
            return int(overrides.get(name, default))
        except Exception:
            return default

    return Config(
        alpaca_api_key=api_key,
        alpaca_secret_key=secret_key,
        alpaca_paper_url=paper_url,
        alpaca_data_feed=data_feed,
        universe_path=os.getenv("UNIVERSE_PATH", "data/sp500.csv"),
        db_path=os.getenv("BROKER_BOT_DB", "data/broker_bot.sqlite"),
        model_dir=os.getenv("MODEL_DIR", "data/models"),
        training_lookback_days=int(os.getenv("TRAIN_LOOKBACK_DAYS", "252")),
        prediction_horizon_days=int(os.getenv("PRED_HORIZON_DAYS", "1")),
        rebalance_top_k=_override_int("rebalance_top_k", int(os.getenv("REBALANCE_TOP_K", "40"))),
        min_long_return=_override("min_long_return", float(os.getenv("MIN_LONG_RETURN", "0.001"))),
        max_short_return=_override("max_short_return", float(os.getenv("MAX_SHORT_RETURN", "-0.001"))),
        max_position_pct=_override("max_position_pct", float(os.getenv("MAX_POSITION_PCT", "0.06"))),
        gross_leverage=_override("gross_leverage", float(os.getenv("GROSS_LEVERAGE", "1.5"))),
        bear_leverage=_override("bear_leverage", float(os.getenv("BEAR_LEVERAGE", "0.6"))),
        rebalance_frequency=os.getenv("REBALANCE_FREQUENCY", "W-FRI"),
        tcost_bps=_override("tcost_bps", float(os.getenv("TCOST_BPS", "5"))),
        min_price=_override("min_price", float(os.getenv("MIN_PRICE", "5"))),
        min_dollar_vol=_override("min_dollar_vol", float(os.getenv("MIN_DOLLAR_VOL", "5000000"))),
        vol_target=_override("vol_target", float(os.getenv("VOL_TARGET", "0.02"))),
        vol_window=_override_int("vol_window", int(os.getenv("VOL_WINDOW", "20"))),
        max_drawdown=_override("max_drawdown", float(os.getenv("MAX_DRAWDOWN", "0.10"))),
        min_leverage=_override("min_leverage", float(os.getenv("MIN_LEVERAGE", "0.2"))),
        drawdown_window=_override_int("drawdown_window", int(os.getenv("DRAWDOWN_WINDOW", "120"))),
        miss_rebalance_prob=_override("miss_rebalance_prob", float(os.getenv("MISS_REBALANCE_PROB", "0.0"))),
        rebalance_delay_days=_override_int("rebalance_delay_days", int(os.getenv("REBALANCE_DELAY_DAYS", "0"))),
        sim_seed=_override_int("sim_seed", int(os.getenv("SIM_SEED", "42"))),
        advisor_overrides_path=overrides_path,
        advisor_auto_apply=auto_apply_flag,
        sector_map_path=sector_map_path,
    )
