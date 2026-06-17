"""Parse dividend history HTML from AAStocks.

Both Traditional Chinese and English mobile/desktop pages are supported.
Both languages return the full static HTML — no JavaScript execution
or headless browser is required.

Chinese:
    https://m.aastocks.com/tc/stocks/analysis/dividend.aspx?symbol=00005
    Headers (8 columns):
        公佈日期 | 年度/截至 | 派息事項 | 派息內容 | 方式 | 除淨日 | 截止過戶日期 | 派息日

English:
    https://m.aastocks.com/en/stocks/analysis/dividend.aspx?symbol=00005
    Headers (8 columns, order may vary):
        Announce Date | Year Ended | Event | Particular | Type |
        Ex-Date | Book Close Date | Payable Date
"""
from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

# Traditional Chinese column headers -> output key.
COLUMN_MAP_TC: dict[str, str] = {
    "公佈日期":       "announce_date",
    "年度/截至":      "year_ended",
    "派息事項":       "event",
    "派息內容":       "particular",
    "方式":           "type",
    "除淨日":         "ex_date",
    "截止過戶日期":   "book_close",
    "派息日":         "payable_date",
}

# English column headers -> output key.  Value is a list because the exact
# English header text may vary slightly between page layouts.
COLUMN_MAP_EN: dict[str, str] = {
    "Announce Date":     "announce_date",
    "Year Ended":        "year_ended",
    "Event":             "event",
    "Particular":        "particular",
    "Dividend Details":  "particular",
    "Type":              "type",
    "Dividend Type":     "type",
    "Ex-Date":           "ex_date",
    "Book Close":        "book_close",
    "Book Close Date":   "book_close",
    "Payable Date":      "payable_date",
}

# Header cells whose presence in the first row identifies the dividend table.
TABLE_HEADER_MARKERS = (
    "Announce Date",
    "Ex-Date",
    "公佈日期",
    "除淨日",
)

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


def _detect_language(header_cells: list[str]) -> str:
    """Return 'en' if the header row looks English, 'tc' otherwise."""
    joined = " ".join(header_cells)
    if "Announce Date" in joined or "Ex-Date" in joined:
        return "en"
    return "tc"


def _build_column_map(header_cells: list[str]) -> dict[str, str]:
    """Return the appropriate COLUMN_MAP based on the detected language."""
    lang = _detect_language(header_cells)
    if lang == "en":
        return COLUMN_MAP_EN
    return COLUMN_MAP_TC


def _map_row(data_cells: list[str], header_cells: list[str], col_map: dict[str, str]) -> dict:
    """Map data row cells to named output fields using header_cells and col_map.

    Parameters
    ----------
    data_cells : list[str]
        The cells of a single data row (e.g. ["2026/05/05", "2026/12", "Interim", ...]).
    header_cells : list[str]
        The cells of the header row (e.g. ["Announce Date", "Year Ended", "Event", ...]).
    col_map : dict[str, str]
        Mapping from header text -> output field name.  Multiple header texts may
        map to the same field; the first matching header in header_cells wins.

    Returns
    -------
    dict
        All unique output field names from col_map, with the cell value at the
        corresponding index (or '' if that column is missing in the data row).
    """
    # Build positional mapping: header text -> column index, keeping the
    # leftmost occurrence of each header.
    header_to_idx: dict[str, int] = {}
    for idx, cell in enumerate(header_cells):
        text = _clean(cell)
        if text in col_map and text not in header_to_idx:
            header_to_idx[text] = idx

    # Collect unique output field names, preserving the first occurrence order.
    field_to_header: dict[str, str] = {}
    for header_text, field_name in col_map.items():
        if field_name not in field_to_header:
            field_to_header[field_name] = header_text

    out: dict[str, str] = {}
    for field_name, header_text in field_to_header.items():
        if header_text in header_to_idx:
            idx = header_to_idx[header_text]
            if idx < len(data_cells):
                out[field_name] = _clean(data_cells[idx])
            else:
                out[field_name] = ""
        else:
            out[field_name] = ""

    return out


def find_dividend_table(soup: BeautifulSoup) -> Optional[Tag]:
    """Locate the dividend history table.

    Looks for a ``<table>`` whose first row contains a known header marker
    such as 公佈日期, Announce Date, or Ex-Date.
    """
    for table in soup.find_all("table"):
        first_row = table.find("tr")
        if not first_row:
            continue
        header_text = first_row.get_text(" ", strip=True)
        if any(marker in header_text for marker in TABLE_HEADER_MARKERS):
            return table
    return None


def normalize_row(mapped: dict, lang: str) -> dict:
    """Convert the mapped raw dict into a clean output dict.

    Applies date normalization and preserves the raw version of date fields.
    """
    announce = mapped.get("announce_date", "")
    year     = mapped.get("year_ended", "")
    event    = mapped.get("event", "")
    particular = mapped.get("particular", "")
    type_    = mapped.get("type", "")
    ex       = mapped.get("ex_date", "")
    book     = mapped.get("book_close", "")
    payable  = mapped.get("payable_date", "")

    return {
        "announce_date":     _to_iso_date(announce),
        "announce_date_raw": announce,
        "year_ended":        _to_iso_year_month(year),
        "year_ended_raw":    year,
        "event":             event,
        "particular":         particular,
        "type":              type_,
        "ex_date":           _to_iso_date(ex),
        "ex_date_raw":       ex,
        "book_close":        _clean(book),
        "payable_date":      _to_iso_date(payable),
        "payable_date_raw":  payable,
        # Internal field used downstream to choose English vs Chinese transform.
        "_lang":             lang,
    }


def parse_dividend_html(html: str, language: str = "tc") -> tuple[list[dict], Optional[str]]:
    """Return (rows, error_message).

    ``rows`` is a list of normalized dicts.  ``error_message`` is ``None``
    on success, otherwise a human-readable reason.

    ``language`` is a hint; if it is "tc" the Chinese column map is tried first,
    otherwise the English one.  In practice, the actual language is re-detected
    from the table header to handle edge cases.

    The returned rows always contain the same 13 columns regardless of language,
    plus an internal ``_lang`` field.
    """
    soup = BeautifulSoup(html, "lxml")
    table = find_dividend_table(soup)
    if table is None:
        return [], "no_table"

    rows_out: list[dict] = []
    header_cells: list[str] = []

    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if not cells or not any(c for c in cells if c):
            continue

        joined = " ".join(cells)

        # First row that matches the header pattern = column header row.
        if any(marker in joined for marker in TABLE_HEADER_MARKERS):
            header_cells = cells
            col_map = _build_column_map(cells)
            continue

        # Skip obvious non-data rows.
        if not any(c for c in cells if c and c != "-"):
            continue

        # Skip rows that are entirely header labels.
        if any(label in joined for label in TABLE_HEADER_MARKERS):
            continue

        mapped = _map_row(cells, header_cells, col_map)
        rows_out.append(normalize_row(mapped, language if language else "tc"))

    if not rows_out:
        return [], "empty_table"
    return rows_out, None
