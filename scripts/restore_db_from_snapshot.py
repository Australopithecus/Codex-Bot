#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from broker_bot.config import load_config
from broker_bot.logging_db import init_db, log_equity, log_trades, log_positions, log_advisor_report


def main() -> None:
    snapshot_path = Path("data/dashboard_snapshot.json")
    if not snapshot_path.exists():
        print("No snapshot found. Skipping restore.")
        return

    data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    config = load_config()
    init_db(config.db_path)

    for row in data.get("equity", []):
        log_equity(
            config.db_path,
            row["ts"],
            float(row["equity"]),
            float(row.get("cash", 0.0)),
            float(row.get("portfolio_value", 0.0)),
            row.get("spy_value"),
        )

    trades = []
    for row in data.get("trades", []):
        trades.append(
            (
                row["ts"],
                row["symbol"],
                row["side"],
                float(row["qty"]),
                row.get("price"),
                None,
                row.get("status"),
            )
        )
    if trades:
        log_trades(config.db_path, trades)

    positions = []
    for row in data.get("positions", []):
        positions.append(
            (
                row["symbol"],
                float(row["qty"]),
                row.get("avg_entry_price"),
                row.get("market_value"),
                row.get("unrealized_pl"),
            )
        )
    if positions:
        # Use current timestamp for position snapshot
        log_positions(config.db_path, data.get("generated_at", ""), positions)

    for row in data.get("advisor_reports", []):
        log_advisor_report(
            config.db_path,
            row["ts"],
            row.get("headline", "Advisor Report"),
            row.get("summary", ""),
            json.dumps(row.get("suggestions", [])),
            json.dumps(row.get("metrics", {})),
            json.dumps(row.get("overrides", {})),
        )

    print("Snapshot restored into local DB")


if __name__ == "__main__":
    main()
