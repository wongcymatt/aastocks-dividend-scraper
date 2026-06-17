"""Scrape dividend history from AAStocks and write per-symbol CSVs.

Usage:
    python scrape_dividend.py                  # scrape every symbol in stocks.txt
    python scrape_dividend.py --symbol 01114   # scrape a single symbol
    python scrape_dividend.py --symbol 00005 --symbol 00700
    python scrape_dividend.py --url-template desktop

Each row in stocks.txt should be a single HK stock symbol, 5-digit
zero-padded (e.g. 01114, 00005).  Lines starting with '#' and blank
lines are ignored.
"""
from __future__ import annotations

import argparse
import csv
import os
import random
import sys
import time
from pathlib import Path
from typing import Iterable

import requests

from parse_dividend import parse_dividend_html

# Default headers.  AAStocks returns a full static HTML response with these,
# so we do not need a real browser.
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
    "Mobile/15E148 Safari/604.1"
)

# Two URL templates.  Both return the same dividend table; mobile is the
# user's preferred target.
URL_TEMPLATES = {
    "mobile": "https://m.aastocks.com/tc/stocks/analysis/dividend.aspx?symbol={symbol}",
    "desktop": "https://www.aastocks.com/tc/stocks/analysis/company-fundamental/dividend-history?symbol={symbol}",
}

# Output column order for CSVs.  Includes a leading 'symbol' so multiple
# per-symbol files can be concatenated and still keep their identity.
OUTPUT_COLUMNS = [
    "symbol",
    "announce_date",
    "announce_date_raw",
    "year_ended",
    "year_ended_raw",
    "event",
    "particular",
    "type",
    "ex_date",
    "ex_date_raw",
    "book_close",
    "payable_date",
    "payable_date_raw",
]

ROOT = Path(__file__).resolve().parent
DEFAULT_STOCKS_FILE = ROOT / "stocks.txt"
DEFAULT_OUTPUT_DIR = ROOT / "output"


def read_symbols(path: Path) -> list[str]:
    """Read symbols from a text file, one per line, ignoring blanks and comments."""
    symbols: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        symbols.append(line)
    return symbols


def fetch_page(symbol: str, url_template: str, session: requests.Session,
               timeout: float = 30.0) -> tuple[int | None, str]:
    """GET the dividend page for ``symbol``.  Returns (status_code, body).

    The body is decoded using the response's apparent encoding.  On error,
    status_code is None and body is the exception message.
    """
    url = url_template.format(symbol=symbol)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-Hant-HK,zh-Hant;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": url,
    }
    try:
        resp = session.get(url, headers=headers, timeout=timeout)
        return resp.status_code, resp.text
    except requests.RequestException as e:
        return None, str(e)


def write_csv(rows: list[dict], symbol: str, output_dir: Path) -> Path:
    """Write rows to ``output/dividend_<symbol>.csv`` with utf-8-sig BOM."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"dividend_{symbol}.csv"
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for row in rows:
            # Augment row with the symbol so the CSV is self-describing.
            full_row = {"symbol": symbol, **row}
            writer.writerow(full_row)
    return out_path


def scrape_one(symbol: str, url_template: str, output_dir: Path,
               session: requests.Session) -> tuple[int, str]:
    """Scrape a single symbol.  Returns (row_count, status)."""
    status, body = fetch_page(symbol, url_template, session)

    if status is None:
        return 0, f"network_error: {body[:80]}"
    if status != 200:
        return 0, f"http_{status}"

    rows, err = parse_dividend_html(body)
    if err == "no_table":
        return 0, "no_table_on_page"
    if err == "empty_table":
        return 0, "table_empty"

    out_path = write_csv(rows, symbol, output_dir)
    return len(rows), f"wrote_{out_path.name}"


def iter_sleep(lo: float = 1.5, hi: float = 3.5) -> None:
    """Sleep a random duration between requests to be polite to the server."""
    time.sleep(random.uniform(lo, hi))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", action="append", help="scrape a single symbol (repeatable)")
    parser.add_argument("--stocks-file", type=Path, default=DEFAULT_STOCKS_FILE,
                        help=f"path to symbols list (default: {DEFAULT_STOCKS_FILE.name})")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help=f"directory for CSV output (default: {DEFAULT_OUTPUT_DIR.name})")
    parser.add_argument("--url-template", choices=sorted(URL_TEMPLATES),
                        default="mobile",
                        help="which AAStocks URL pattern to use (default: mobile)")
    parser.add_argument("--delay-min", type=float, default=1.5,
                        help="minimum delay between requests in seconds (default 1.5)")
    parser.add_argument("--delay-max", type=float, default=3.5,
                        help="maximum delay between requests in seconds (default 3.5)")
    args = parser.parse_args(argv)

    if args.symbol:
        symbols: list[str] = list(dict.fromkeys(args.symbol))  # de-dupe, preserve order
    else:
        if not args.stocks_file.exists():
            print(f"ERROR: stocks file not found: {args.stocks_file}", file=sys.stderr)
            return 2
        symbols = read_symbols(args.stocks_file)
        if not symbols:
            print(f"ERROR: no symbols in {args.stocks_file}", file=sys.stderr)
            return 2

    url_template = URL_TEMPLATES[args.url_template]
    print(f"Scraping {len(symbols)} symbol(s) via {args.url_template}: {url_template}")
    print(f"Output dir: {args.output_dir}")
    print(f"Delay between requests: {args.delay_min:.1f}s – {args.delay_max:.1f}s")
    print()

    session = requests.Session()
    successes: list[str] = []
    failures: list[tuple[str, str]] = []
    total_rows = 0

    for i, sym in enumerate(symbols, 1):
        print(f"[{i}/{len(symbols)}] {sym} ...", end=" ", flush=True)
        n, status = scrape_one(sym, url_template, args.output_dir, session)
        print(status)
        if n > 0:
            successes.append(sym)
            total_rows += n
        else:
            failures.append((sym, status))

        if i < len(symbols):
            iter_sleep(args.delay_min, args.delay_max)

    print()
    print(f"Done.  {len(successes)}/{len(symbols)} symbols OK, {total_rows} total rows scraped.")
    if failures:
        print("Failures:")
        for sym, reason in failures:
            print(f"  {sym}: {reason}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
