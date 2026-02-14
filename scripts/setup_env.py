from __future__ import annotations

import os
from getpass import getpass
from pathlib import Path

ENV_PATH = Path(".env")


def prompt_value(label: str, default: str | None = None, secret: bool = False) -> str:
    while True:
        prompt = f"{label}"
        if default:
            prompt += f" [{default}]"
        prompt += ": "
        value = getpass(prompt) if secret else input(prompt)
        value = value.strip()
        if not value and default is not None:
            return default
        if value:
            return value
        print("Value cannot be empty. Please try again.")


def main() -> None:
    if ENV_PATH.exists():
        overwrite = input(".env already exists. Overwrite? [y/N]: ").strip().lower()
        if overwrite not in {"y", "yes"}:
            print("Aborting without changes.")
            return

    api_key = prompt_value("Alpaca API Key")
    secret_key = prompt_value("Alpaca Secret Key", secret=True)
    paper_url = prompt_value("Alpaca Paper URL", default="https://paper-api.alpaca.markets")
    data_feed = prompt_value("Alpaca Data Feed (iex or sip)", default="iex")

    content = "\n".join(
        [
            f"ALPACA_API_KEY={api_key}",
            f"ALPACA_SECRET_KEY={secret_key}",
            f"ALPACA_PAPER_URL={paper_url}",
            f"ALPACA_DATA_FEED={data_feed}",
            "",
            "UNIVERSE_PATH=data/sp500.csv",
            "BROKER_BOT_DB=data/broker_bot.sqlite",
            "MODEL_DIR=data/models",
            "",
            "TRAIN_LOOKBACK_DAYS=252",
            "PRED_HORIZON_DAYS=1",
            "REBALANCE_TOP_K=40",
            "MIN_LONG_RETURN=0.001",
            "MAX_SHORT_RETURN=-0.001",
            "MAX_POSITION_PCT=0.06",
            "GROSS_LEVERAGE=1.5",
            "BEAR_LEVERAGE=0.6",
            "REBALANCE_FREQUENCY=W-FRI",
            "TCOST_BPS=5",
            "ADVISOR_OVERRIDES_PATH=data/advisor_overrides.json",
            "ADVISOR_AUTO_APPLY=1",
            "SECTOR_MAP_PATH=data/sector_map.csv",
            "API_TOKEN=change_me",
            "MIN_PRICE=5",
            "MIN_DOLLAR_VOL=5000000",
            "VOL_TARGET=0.02",
            "VOL_WINDOW=20",
            "MAX_DRAWDOWN=0.10",
            "MIN_LEVERAGE=0.2",
            "DRAWDOWN_WINDOW=120",
            "MISS_REBALANCE_PROB=0.0",
            "REBALANCE_DELAY_DAYS=0",
            "SIM_SEED=42",
            "LLM_ENABLED=0",
            "LLM_MODEL=gpt-5-mini",
            "OPENAI_API_KEY=your_openai_key_here",
            "",
        ]
    )

    ENV_PATH.write_text(content, encoding="utf-8")
    os.chmod(ENV_PATH, 0o600)
    print(".env written with restricted permissions (600).")


if __name__ == "__main__":
    main()
