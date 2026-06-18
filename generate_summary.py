#!/usr/bin/env python3
"""Generate a summary CSV listing every ticker and whether it has dividend history."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STOCKS_FILE = ROOT / "stocks.txt"
OUTPUT_DIR = ROOT / "output"

# Read all tickers from stocks.txt
tickers = []
for raw in STOCKS_FILE.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    tickers.append(line)

# Build set of scraped tickers
scraped = {p.stem.removeprefix("dividend_") for p in OUTPUT_DIR.glob("dividend_*.csv")}

# Write summary CSV
out_path = OUTPUT_DIR / "dividend_summary.csv"
total = len(tickers)
with out_path.open("w", encoding="utf-8-sig", newline="") as f:
    f.write("symbol,has_dividend_csv,row_count,csv_path\n")
    for t in tickers:
        csv_path = OUTPUT_DIR / f"dividend_{t}.csv"
        has_csv = t in scraped
        if has_csv:
            try:
                # Count data rows (total lines - 1 header)
                row_count = csv_path.read_text(encoding="utf-8-sig").count("\n") - 1
            except Exception:
                row_count = 0
            f.write(f"{t},Yes,{row_count},output/dividend_{t}.csv\n")
        else:
            f.write(f"{t},No,0,\n")

# Stats
with_data = sum(1 for t in tickers if t in scraped)
no_data = total - with_data
print(f"Summary written to: {out_path}")
print(f"Total tickers : {total}")
print(f"With CSV      : {with_data}")
print(f"No CSV        : {no_data}")
