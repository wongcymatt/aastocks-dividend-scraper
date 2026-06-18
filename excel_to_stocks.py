"""Extract unique HK stock tickers from HKG_Ticker_List_20260618.xlsx.

Reads the ticker_padding column, strips the "-HK" suffix, de-duplicates,
and writes one zero-padded 5-digit symbol per line to stocks.txt.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import openpyxl
except ImportError:
    print("ERROR: openpyxl is not installed. Run: pip install openpyxl", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent
EXCEL_PATH = ROOT / "HKG_Ticker_List_20260618.xlsx"
OUTPUT_PATH = ROOT / "stocks.txt"


def main() -> int:
    wb = openpyxl.load_workbook(EXCEL_PATH, read_only=True, data_only=True)
    ws = wb.active

    headers: list[str] = []
    ticker_idx: int | None = None
    symbols_ordered: list[str] = []
    seen: set[str] = set()

    for row in ws.iter_rows(values_only=True):
        if headers:
            ticker_raw = row[ticker_idx] if ticker_idx is not None else None
            if ticker_raw:
                sym = str(ticker_raw).replace("-HK", "").strip()
                # Validate: must be 5-digit zero-padded.
                if len(sym) == 5 and sym.isdigit() and sym not in seen:
                    seen.add(sym)
                    symbols_ordered.append(sym)
        else:
            headers = list(row)
            try:
                ticker_idx = headers.index("ticker_padding")
            except ValueError:
                print(f"ERROR: 'ticker_padding' column not found in {EXCEL_PATH}", file=sys.stderr)
                print(f"Available columns: {headers}", file=sys.stderr)
                wb.close()
                return 1

    wb.close()

    # Sort for clean, stable output.
    symbols_ordered.sort()

    OUTPUT_PATH.write_text(
        "# HK stock symbols — auto-generated from HKG_Ticker_List_20260618.xlsx\n"
        "# 5-digit zero-padded, one per line.  Lines starting with '#' are ignored.\n"
        + "\n".join(symbols_ordered)
        + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {len(symbols_ordered)} unique tickers to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
