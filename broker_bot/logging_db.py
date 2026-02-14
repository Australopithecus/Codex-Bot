from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable


def init_db(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS equity (
                ts TEXT PRIMARY KEY,
                equity REAL NOT NULL,
                cash REAL NOT NULL,
                portfolio_value REAL NOT NULL,
                spy_value REAL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty REAL NOT NULL,
                price REAL,
                order_id TEXT,
                status TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                symbol TEXT NOT NULL,
                qty REAL NOT NULL,
                avg_entry_price REAL,
                market_value REAL,
                unrealized_pl REAL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                symbol TEXT NOT NULL,
                score REAL NOT NULL,
                signal TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS advisor_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                headline TEXT,
                summary TEXT,
                suggestions TEXT,
                metrics TEXT,
                overrides TEXT
            )
            """
        )


def log_equity(db_path: str, ts: str, equity: float, cash: float, portfolio_value: float, spy_value: float | None) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO equity (ts, equity, cash, portfolio_value, spy_value) VALUES (?, ?, ?, ?, ?)",
            (ts, equity, cash, portfolio_value, spy_value),
        )


def log_trades(db_path: str, rows: Iterable[tuple[str, str, float, float | None, str | None, str | None]]) -> None:
    with sqlite3.connect(db_path) as conn:
        normalized = []
        for ts, symbol, side, qty, price, order_id, status in rows:
            price_val = float(price) if price is not None else None
            qty_val = float(qty)
            order_id_val = str(order_id) if order_id is not None else None
            status_val = str(status) if status is not None else None
            normalized.append((ts, symbol, side, qty_val, price_val, order_id_val, status_val))
        conn.executemany(
            "INSERT INTO trades (ts, symbol, side, qty, price, order_id, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            normalized,
        )


def log_positions(db_path: str, ts: str, rows: Iterable[tuple[str, float, float | None, float | None, float | None]]) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO positions (ts, symbol, qty, avg_entry_price, market_value, unrealized_pl) VALUES (?, ?, ?, ?, ?, ?)",
            [(ts, *row) for row in rows],
        )


def log_signals(db_path: str, ts: str, rows: Iterable[tuple[str, float, str]]) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO signals (ts, symbol, score, signal) VALUES (?, ?, ?, ?)",
            [(ts, *row) for row in rows],
        )


def read_latest_equity(db_path: str, limit: int = 120) -> list[tuple[str, float, float, float, float | None]]:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "SELECT ts, equity, cash, portfolio_value, spy_value FROM equity ORDER BY ts DESC LIMIT ?",
            (limit,),
        )
        return cursor.fetchall()


def read_latest_positions(db_path: str, limit: int = 200) -> list[tuple[str, float, float | None, float | None, float | None]]:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "SELECT symbol, qty, avg_entry_price, market_value, unrealized_pl FROM positions ORDER BY ts DESC LIMIT ?",
            (limit,),
        )
        return cursor.fetchall()


def read_latest_trades(db_path: str, limit: int = 200) -> list[tuple[str, str, str, float, float | None, str | None]]:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "SELECT ts, symbol, side, qty, price, status FROM trades ORDER BY ts DESC LIMIT ?",
            (limit,),
        )
        return cursor.fetchall()


def log_advisor_report(
    db_path: str,
    ts: str,
    headline: str,
    summary: str,
    suggestions_json: str,
    metrics_json: str,
    overrides_json: str,
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO advisor_reports (ts, headline, summary, suggestions, metrics, overrides) VALUES (?, ?, ?, ?, ?, ?)",
            (ts, headline, summary, suggestions_json, metrics_json, overrides_json),
        )


def read_latest_advisor_reports(db_path: str, limit: int = 10) -> list[tuple[str, str, str, str, str, str]]:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "SELECT ts, headline, summary, suggestions, metrics, overrides FROM advisor_reports ORDER BY ts DESC LIMIT ?",
            (limit,),
        )
        return cursor.fetchall()
