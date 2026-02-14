from __future__ import annotations

import tkinter as tk
from datetime import datetime

from .logging_db import read_latest_equity, read_latest_positions, read_latest_trades


class BrokerBotDashboard(tk.Tk):
    def __init__(self, db_path: str) -> None:
        super().__init__()
        self.title("Broker Bot Dashboard")
        self.geometry("980x700")
        self.db_path = db_path
        self.configure(bg="#f8fafc")
        self._build_layout()
        # Defer refresh so the UI renders even if refresh errors.
        self.after(0, self._safe_refresh)

    def _build_layout(self) -> None:
        self.header_label = tk.Label(
            self,
            text="Broker Bot (Paper Trading)",
            font=("Helvetica", 18, "bold"),
            bg="#fde047",
            fg="#0f172a",
            relief="solid",
            bd=1,
        )
        self.header_label.pack(pady=10, ipadx=6, ipady=4, fill=tk.X)

        self.summary_var = tk.StringVar(value="Loading...")
        self.summary_label = tk.Label(
            self,
            textvariable=self.summary_var,
            font=("Helvetica", 11),
            bg="#e0f2fe",
            fg="#0f172a",
            relief="solid",
            bd=1,
        )
        self.summary_label.pack(pady=5, ipadx=6, ipady=3, fill=tk.X)

        self.chart = tk.Canvas(self, width=900, height=200, bg="#0f172a", highlightthickness=0)
        self.chart.pack(pady=10, fill=tk.X)
        self.chart.create_rectangle(20, 20, 200, 80, fill="#22c55e", outline="")
        self.chart.create_text(110, 50, text="Canvas OK", fill="#0f172a", font=("Helvetica", 12, "bold"))

        # Diagnostic text to verify rendering in case data load fails.
        self.diagnostic_label = tk.Label(
            self,
            text="UI render check: if you can read this, Tk is drawing widgets.",
            font=("Helvetica", 10),
            bg="#fecdd3",
            fg="#334155",
            relief="solid",
            bd=1,
        )
        self.diagnostic_label.pack(pady=4, ipadx=6, ipady=2, fill=tk.X)

        self.tables_frame = tk.Frame(self, bg="#f8fafc")
        self.tables_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.positions_label = tk.Label(
            self.tables_frame,
            text="Positions",
            font=("Helvetica", 12, "bold"),
            bg="#bbf7d0",
            fg="#0f172a",
            relief="solid",
            bd=1,
        )
        self.positions_label.pack(fill=tk.X)
        self.positions_list = self._build_list(self.tables_frame, width=120, height=10)
        self.positions_list.pack(fill=tk.BOTH, expand=True, pady=6)

        self.trades_label = tk.Label(
            self.tables_frame,
            text="Trades",
            font=("Helvetica", 12, "bold"),
            bg="#bbf7d0",
            fg="#0f172a",
            relief="solid",
            bd=1,
        )
        self.trades_label.pack(fill=tk.X)
        self.trades_list = self._build_list(self.tables_frame, width=120, height=10)
        self.trades_list.pack(fill=tk.BOTH, expand=True, pady=6)

        self.controls_frame = tk.Frame(self, bg="#f8fafc")
        self.controls_frame.pack(pady=8)
        self.refresh_button = tk.Button(self.controls_frame, text="Refresh", command=self._refresh)
        self.refresh_button.pack()

    def _build_list(self, parent: tk.Frame, width: int, height: int) -> tk.Listbox:
        listbox = tk.Listbox(parent, width=width, height=height, font=("Courier", 10), bg="#f1f5f9", fg="#0f172a")
        return listbox

    def _draw_equity_curve(self, points: list[tuple[str, float]]) -> None:
        self.chart.delete("all")
        if len(points) < 2:
            self.chart.create_text(450, 100, text="No equity history yet", fill="#e2e8f0")
            return
        values = [p[1] for p in points]
        min_val, max_val = min(values), max(values)
        if max_val == min_val:
            max_val += 1.0

        w = int(self.chart["width"])
        h = int(self.chart["height"])
        pad = 20

        def scale_x(i: int) -> float:
            return pad + (w - 2 * pad) * (i / (len(values) - 1))

        def scale_y(val: float) -> float:
            return h - pad - (h - 2 * pad) * ((val - min_val) / (max_val - min_val))

        for i in range(len(values) - 1):
            self.chart.create_line(
                scale_x(i),
                scale_y(values[i]),
                scale_x(i + 1),
                scale_y(values[i + 1]),
                fill="#38bdf8",
                width=2,
            )

        self.chart.create_text(60, 12, text=f"Min: {min_val:.2f}", fill="#e2e8f0")
        self.chart.create_text(160, 12, text=f"Max: {max_val:.2f}", fill="#e2e8f0")

    def _refresh(self) -> None:
        equity_rows = read_latest_equity(self.db_path, limit=180)
        if equity_rows:
            latest = equity_rows[0]
            ts = datetime.fromisoformat(latest[0]).strftime("%Y-%m-%d %H:%M")
            spy_text = f" | SPY Close: ${latest[4]:,.2f}" if latest[4] else ""
            self.summary_var.set(
                f"As of {ts} | Equity: ${latest[1]:,.2f} | Cash: ${latest[2]:,.2f} | Portfolio: ${latest[3]:,.2f}{spy_text}"
            )
        else:
            self.summary_var.set("No equity snapshots yet. Run the bot to log data.")

        points = [(row[0], row[1]) for row in reversed(equity_rows)]
        self._draw_equity_curve(points)

        self._populate_list(self.positions_list, read_latest_positions(self.db_path, limit=200), header=[
            "Symbol", "Qty", "Avg Entry", "Mkt Value", "Unreal P/L"
        ])
        self._populate_list(self.trades_list, read_latest_trades(self.db_path, limit=200), header=[
            "Time", "Symbol", "Side", "Qty", "Price", "Status"
        ])

    def _safe_refresh(self) -> None:
        try:
            self._refresh()
        except Exception as exc:  # noqa: BLE001
            self.summary_var.set(f"Dashboard refresh error: {exc}")

    def _populate_list(self, listbox: tk.Listbox, rows: list[tuple], header: list[str]) -> None:
        listbox.delete(0, tk.END)
        listbox.insert(tk.END, " | ".join(header))
        listbox.insert(tk.END, "-" * 100)
        for row in rows:
            listbox.insert(tk.END, " | ".join(str(item) for item in row))


def launch_dashboard(db_path: str) -> None:
    app = BrokerBotDashboard(db_path)
    app.mainloop()
