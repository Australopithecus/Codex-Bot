#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from broker_bot.config import load_config
from broker_bot.logging_db import (
    init_db,
    read_latest_equity,
    read_latest_positions,
    read_latest_trades,
    read_latest_advisor_reports,
)


def main() -> None:
    config = load_config()
    init_db(config.db_path)

    equity_rows = list(reversed(read_latest_equity(config.db_path, limit=365)))
    trades_rows = list(reversed(read_latest_trades(config.db_path, limit=1000)))
    positions_rows = read_latest_positions(config.db_path, limit=500)
    advisor_rows = read_latest_advisor_reports(config.db_path, limit=20)

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "equity": [
            {
                "ts": row[0],
                "equity": row[1],
                "cash": row[2],
                "portfolio_value": row[3],
                "spy_value": row[4],
            }
            for row in equity_rows
        ],
        "trades": [
            {
                "ts": row[0],
                "symbol": row[1],
                "side": row[2],
                "qty": row[3],
                "price": row[4],
                "status": row[5],
            }
            for row in trades_rows
        ],
        "positions": [
            {
                "symbol": row[0],
                "qty": row[1],
                "avg_entry_price": row[2],
                "market_value": row[3],
                "unrealized_pl": row[4],
            }
            for row in positions_rows
        ],
        "advisor_reports": [
            {
                "ts": row[0],
                "headline": row[1],
                "summary": row[2],
                "suggestions": json.loads(row[3]) if row[3] else [],
                "metrics": json.loads(row[4]) if row[4] else {},
                "overrides": json.loads(row[5]) if row[5] else {},
            }
            for row in advisor_rows
        ],
    }

    out_path = Path("data/dashboard_snapshot.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote snapshot to {out_path}")


if __name__ == "__main__":
    main()
