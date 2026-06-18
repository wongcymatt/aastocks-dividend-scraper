"""Scrape dividend history from AAStocks and write per-symbol CSVs.

Usage:
    python scrape_dividend.py                  # scrape every symbol in stocks.txt (English, with transform)
    python scrape_dividend.py --symbol 01114   # scrape a single symbol
    python scrape_dividend.py --symbol 00005 --symbol 00700
    python scrape_dividend.py --lang tc        # Traditional Chinese page (with transform)
    python scrape_dividend.py --lang en --symbol 00005 --no-transform  # English page, raw output

Each row in stocks.txt should be a single HK stock symbol, 5-digit
zero-padded (e.g. 01114, 00005).  Lines starting with '#' and blank
lines are ignored.
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

import requests

from parse_dividend import parse_dividend_html

# Default headers for Traditional Chinese pages (static HTML, no browser needed).
USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
    "Mobile/15E148 Safari/604.1"
)

# URL templates keyed by (layout, language).
# layout: "mobile" | "desktop"
# language: "tc" | "en"
URL_TEMPLATES = {
    ("mobile", "tc"):  "https://m.aastocks.com/tc/stocks/analysis/dividend.aspx?symbol={symbol}",
    ("desktop", "tc"): "https://www.aastocks.com/tc/stocks/analysis/company-fundamental/dividend-history?symbol={symbol}",
    ("mobile", "en"):  "https://m.aastocks.com/en/stocks/analysis/dividend.aspx?symbol={symbol}",
    ("desktop", "en"): "https://www.aastocks.com/en/stocks/analysis/company-fundamental/dividend-history?symbol={symbol}",
}

# Raw output column order for CSVs (--no-transform mode).
RAW_OUTPUT_COLUMNS = [
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


def fetch_page_tc(symbol: str, layout: str, session: requests.Session,
                  timeout: float = 30.0) -> tuple[int | None, str]:
    """GET the Traditional Chinese dividend page. Returns (status_code, body).

    The Chinese pages return full static HTML; no browser needed.
    """
    url = URL_TEMPLATES[(layout, "tc")].format(symbol=symbol)
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


def fetch_page_en(symbol: str, layout: str, session: requests.Session,
                  timeout: float = 30.0) -> tuple[int | None, str]:
    """GET the English dividend page. Returns (status_code, body).

    The English page returns full static HTML with the dividend table embedded.
    The key is Accept-Language: en-US,en;q=0.9 to get English content.
    """
    url = URL_TEMPLATES[(layout, "en")].format(symbol=symbol)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": url,
    }
    try:
        resp = session.get(url, headers=headers, timeout=timeout)
        return resp.status_code, resp.text
    except requests.RequestException as e:
        return None, str(e)


def write_csv(rows: list[dict], symbol: str, output_dir: Path,
              columns: list[str]) -> Path:
    """Write rows to ``output/dividend_<symbol>.csv`` with utf-8-sig BOM."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"dividend_{symbol}.csv"
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            full_row = {"symbol": symbol, **row}
            writer.writerow(full_row)
    return out_path


def scrape_one(symbol: str, layout: str, language: str, output_dir: Path,
               session: requests.Session,
               transform: bool) -> tuple[int, str]:
    """Scrape a single symbol. Returns (row_count, status)."""
    if language == "en":
        status, body = fetch_page_en(symbol, layout, session)
    else:
        status, body = fetch_page_tc(symbol, layout, session)

    if status is None:
        return 0, f"network_error: {body[:80]}"
    if status != 200:
        return 0, f"http_{status}"

    rows, err = parse_dividend_html(body, language=language)
    if err == "no_table":
        return 0, "no_table_on_page"
    if err == "empty_table":
        return 0, "table_empty"

    if transform:
        from transform_dividend import transform_rows
        rows = transform_rows(rows, symbol)
        columns = transform_rows.OUTPUT_COLUMNS
    else:
        columns = RAW_OUTPUT_COLUMNS

    out_path = write_csv(rows, symbol, output_dir, columns)
    return len(rows), f"wrote_{out_path.name}"


def iter_sleep(lo: float = 1.5, hi: float = 3.5) -> None:
    """Sleep a random duration between requests to be polite to the server."""
    time.sleep(random.uniform(lo, hi))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", action="append",
                        help="scrape a single symbol (repeatable)")
    parser.add_argument("--stocks-file", type=Path, default=DEFAULT_STOCKS_FILE,
                        help=f"path to symbols list (default: {DEFAULT_STOCKS_FILE.name})")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help=f"directory for CSV output (default: {DEFAULT_OUTPUT_DIR.name})")
    parser.add_argument("--lang", choices=["tc", "en"], default="en",
                        help="page language: en=English (default), tc=Traditional Chinese")
    parser.add_argument("--layout", choices=["mobile", "desktop"], default="mobile",
                        help="page layout (default: mobile)")
    parser.add_argument("--transform", action=argparse.BooleanOptionalAction, default=True,
                        help="run Step 1 transform: classify events + extract cash dividend amounts "
                             "(default: enabled). Use --no-transform to get raw scraped output.")
    parser.add_argument("--delay-min", type=float, default=1.5,
                        help="minimum delay between requests in seconds (default 1.5)")
    parser.add_argument("--delay-max", type=float, default=3.5,
                        help="maximum delay between requests in seconds (default 3.5)")
    parser.add_argument("--workers", type=int, default=10,
                        help="number of parallel workers (default 10)")
    parser.add_argument("--resume", action="store_true", default=True,
                        help="skip symbols with existing CSV output (default: enabled)")
    parser.add_argument("--no-resume", dest="resume", action="store_false",
                        help="disable resume - re-scrape all symbols")
    args = parser.parse_args(argv)

    if args.symbol:
        symbols: list[str] = list(dict.fromkeys(args.symbol))
    else:
        if not args.stocks_file.exists():
            print(f"ERROR: stocks file not found: {args.stocks_file}", file=sys.stderr)
            return 2
        symbols = read_symbols(args.stocks_file)
        if not symbols:
            print(f"ERROR: no symbols in {args.stocks_file}", file=sys.stderr)
            return 2

    layout = args.layout
    lang = args.lang
    transform = args.transform

    if args.resume:
        existing = {p.stem.removeprefix("dividend_")
                    for p in args.output_dir.glob("dividend_*.csv")}
        skipped = [s for s in symbols if s in existing]
        if skipped:
            print(f"Resume: skipping {len(skipped)} already-scraped symbol(s)")
        symbols = [s for s in symbols if s not in existing]

    if not symbols:
        print("No symbols to scrape (all already done).")
        return 0

    lang_label = "English" if lang == "en" else "Traditional Chinese"
    print(f"Scraping {len(symbols)} symbol(s) | layout={layout} | lang={lang_label} | transform={transform}")
    print(f"Output dir: {args.output_dir}")
    print(f"Workers: {args.workers} | Delay: {args.delay_min:.1f}s - {args.delay_max:.1f}s")
    print()

    session = requests.Session()
    successes: list[str] = []
    failures: list[tuple[str, str]] = []
    total_rows = 0

    print_lock = Lock()
    done_count = [0]  # mutable int for closure

    def worker(sym: str) -> tuple[str, int, str]:
        """Worker function for a single symbol (runs in thread pool)."""
        time.sleep(random.uniform(args.delay_min, args.delay_max))
        n, status = scrape_one(sym, layout, lang, args.output_dir, session, transform)
        with print_lock:
            done_count[0] += 1
            print(f"[{done_count[0]}/{len(symbols)}] {sym} ... {status}")
        return sym, n, status

    total = len(symbols)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(worker, sym): sym for sym in symbols}
        for future in as_completed(futures):
            sym, n, status = future.result()
            if n > 0:
                successes.append(sym)
                total_rows += n
            else:
                failures.append((sym, status))

    print()
    print(f"Done.  {len(successes)}/{total} symbols OK, {total_rows} total rows scraped.")
    if failures:
        print("Failures:")
        for sym, reason in failures:
            print(f"  {sym}: {reason}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
