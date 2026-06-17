"""Parse dividend history HTML from AAStocks.

The mobile and desktop dividend pages both embed the full dividend history
table in the static HTML response (no JavaScript required). The table has
class ``cnhk-cf tblM ...`` and 8 columns in Traditional Chinese:

    0  公佈日期       Announce Date
    1  年度/截至      Year Ended
    2  派息事項       Event
    3  派息內容       Particular (e.g. "股息：港元 0.8000")
    4  方式           Type ("現金" = Cash, "-" = none, etc.)
    5  除淨日         Ex-Date
    6  截止過戶日期   Book Close (may be a range "2024/08/15-2024/08/19")
    7  派息日         Payable Date
"""
from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

# Traditional Chinese column names -> English keys used in the output dict.
COLUMN_MAP = {
    "公佈日期": "announce_date",
    "年度/截至": "year_ended",
    "派息事項": "event",
    "派息內容": "particular",
    "方式": "type",
    "除淨日": "ex_date",
    "截止過戶日期": "book_close",
    "派息日": "payable_date",
}

# Patterns to recognize the dividend history table regardless of language variant.
TABLE_HEADER_MARKERS = ("公佈日期", "Announce Date", "Ex-Date")

# Date string -> ISO yyyy-mm-dd.  AAStocks uses yyyy/mm/dd.
_DATE_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")
_YEARMONTH_RE = re.compile(r"(\d{4})/(\d{1,2})")
_PLACEHOLDER = "-"


def _clean(text: str) -> str:
    """Collapse whitespace and strip."""
    return re.sub(r"\s+", " ", text or "").strip()


def _to_iso_date(value: str) -> str:
    """Convert '2025/08/22' -> '2025-08-22'.  Returns empty string for '-'."""
    value = _clean(value)
    if not value or value == _PLACEHOLDER:
        return ""
    m = _DATE_RE.search(value)
    if not m:
        return value
    y, mo, d = m.groups()
    return f"{y}-{int(mo):02d}-{int(d):02d}"


def _to_iso_year_month(value: str) -> str:
    """Convert '2025/12' -> '2025-12'.  Returns empty string for '-'."""
    value = _clean(value)
    if not value or value == _PLACEHOLDER:
        return ""
    m = _YEARMONTH_RE.search(value)
    if not m:
        return value
    y, mo = m.groups()
    return f"{y}-{int(mo):02d}"


def find_dividend_table(soup: BeautifulSoup) -> Optional[Tag]:
    """Locate the dividend history table.

    Looks for a ``<table>`` whose first row contains a known header marker
    such as 公佈日期 or Announce Date.  This is more robust than walking
    up from a title element, because the page has multiple divs whose text
    contains "派息紀錄" (e.g. the side navigation link).
    """
    for table in soup.find_all("table"):
        first_row = table.find("tr")
        if not first_row:
            continue
        header_text = first_row.get_text(" ", strip=True)
        if any(marker in header_text for marker in TABLE_HEADER_MARKERS):
            return table
    return None


def normalize_row(cells: list[str]) -> dict:
    """Convert 8 raw cell strings into a clean output dict.

    The Particular cell often contains markup like
    ``<a href="...">股息</a>：港元 0.8000`` which has already been flattened
    to text by the time we see it; we keep the cleaned text.
    """
    # Pad / trim to exactly 8 cells so positional indexing is safe.
    padded = (cells + [""] * 8)[:8]
    announce, year, event, particular, type_, ex, book, payable = (
        _clean(c) for c in padded
    )

    return {
        "announce_date": _to_iso_date(announce),
        "announce_date_raw": announce,
        "year_ended": _to_iso_year_month(year),
        "year_ended_raw": year,
        "event": event,
        "particular": particular,
        "type": type_,
        "ex_date": _to_iso_date(ex),
        "ex_date_raw": ex,
        "book_close": _clean(book),
        "payable_date": _to_iso_date(payable),
        "payable_date_raw": payable,
    }


def parse_dividend_html(html: str) -> tuple[list[dict], Optional[str]]:
    """Return (rows, error_message).

    ``rows`` is a list of normalized dicts.  ``error_message`` is ``None``
    on success, otherwise a human-readable reason ("no_table",
    "empty_table", "http_status_...").
    """
    soup = BeautifulSoup(html, "lxml")
    table = find_dividend_table(soup)
    if table is None:
        return [], "no_table"

    rows: list[dict] = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if not cells or not any(cells):
            continue
        # Skip the header row: every cell text is one of the column names.
        if any(marker in " ".join(cells) for marker in TABLE_HEADER_MARKERS):
            continue
        rows.append(normalize_row(cells))

    if not rows:
        return [], "empty_table"
    return rows, None
