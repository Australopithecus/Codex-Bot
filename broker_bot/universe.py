import csv
from pathlib import Path


def load_universe(path: str) -> list[str]:
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Universe file not found: {path}. Create a CSV with a 'symbol' column."
        )

    symbols: list[str] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "symbol" not in [f.lower() for f in reader.fieldnames]:
            raise ValueError("Universe CSV must include a 'symbol' column header.")
        for row in reader:
            symbol = (row.get("symbol") or row.get("Symbol") or "").strip().upper()
            if symbol:
                symbols.append(symbol)

    if not symbols:
        raise ValueError("Universe CSV contains no symbols.")

    return sorted(set(symbols))
