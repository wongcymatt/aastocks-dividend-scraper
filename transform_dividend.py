"""Transform raw AAStocks dividend rows into structured data.

Step 1 pipeline:
  1. Classify every row into an event category (cash dividend, bonus shares,
     rights issue, stock split, in-specie distribution, no dividend, etc.).
  2. For cash dividend rows, extract the primary amount + currency and any
     HKD-equivalent amount listed in the source.
  3. For multi-currency stocks (e.g. HSBC), capture all offered currency
     options and mark which ones are "electable" (shareholder can choose).

One output row is produced per input row.  Cash dividends that need to be
represented in multiple currencies (e.g. USD + HKD) are emitted as separate
currency_option rows, keeping the full amount information per currency.

Usage:
    from transform_dividend import transform_rows
    rows, _ = parse_dividend_html(body, language="en")
    out = transform_rows(rows, "00005")
"""
from __future__ import annotations

import json
import re
from typing import Literal

# ---------------------------------------------------------------------------
# Event category taxonomy
# ---------------------------------------------------------------------------

class EventCategory:
    DIVIDEND           = "DIVIDEND"
    BONUS_SHARES       = "BONUS_SHARES"
    RIGHTS_ISSUE       = "RIGHTS_ISSUE"
    STOCK_SPLIT        = "STOCK_SPLIT"
    INSPECIE           = "INSPECIE"
    NO_DIVIDEND        = "NO_DIVIDEND"
    PREFERRED_OFFERING  = "PREFERRED_OFFERING"
    CORPORATE_ACTION   = "CORPORATE_ACTION"


# Chinese-language patterns (for --lang tc source).
_CATEGORY_PATTERNS_TC: list[tuple[str, str, re.RegexFlag | int]] = [
    (EventCategory.NO_DIVIDEND,       r"無派息",                     re.IGNORECASE),
    (EventCategory.DIVIDEND,          r"股息[：:]",                  0),
    (EventCategory.DIVIDEND,          r"特別股息",                   0),
    (EventCategory.BONUS_SHARES,      r"紅股",                       0),
    (EventCategory.RIGHTS_ISSUE,      r"供股",                       0),
    (EventCategory.STOCK_SPLIT,       r"股份拆細",                   0),
    (EventCategory.STOCK_SPLIT,       r"股份合併",                   0),
    (EventCategory.INSPECIE,          r"實物分派",                   0),
    (EventCategory.INSPECIE,          r"以實物方式分派",              0),
    (EventCategory.PREFERRED_OFFERING, r"優先售股",                  0),
]

# English-language patterns (for --lang en source).
_CATEGORY_PATTERNS_EN: list[tuple[str, str, re.RegexFlag | int]] = [
    (EventCategory.NO_DIVIDEND,       r"No Dividend",               re.IGNORECASE),
    (EventCategory.DIVIDEND,          r"^D\s*[:：]\s*",              0),
    (EventCategory.DIVIDEND,          r"^SD\s*[:：]\s*",             0),  # Special Dividend, AAStocks shorthand
    (EventCategory.DIVIDEND,          r"^Dividend:",                0),
    (EventCategory.DIVIDEND,          r"Special Dividend:",         re.IGNORECASE),
    (EventCategory.DIVIDEND,          r"^Interim Dividend:",        0),
    (EventCategory.DIVIDEND,          r"^Final Dividend:",          0),
    (EventCategory.BONUS_SHARES,      r"Bonus",                    re.IGNORECASE),
    (EventCategory.RIGHTS_ISSUE,      r"Rights Issue",             re.IGNORECASE),
    (EventCategory.STOCK_SPLIT,       r"Stock Split",              re.IGNORECASE),
    (EventCategory.INSPECIE,          r"In Specie",                re.IGNORECASE),
    (EventCategory.PREFERRED_OFFERING, r"Preferential",            re.IGNORECASE),
]


def _classify_event(particular: str, lang: str) -> str:
    """Return the event category for ``particular``."""
    patterns = _CATEGORY_PATTERNS_EN if lang == "en" else _CATEGORY_PATTERNS_TC
    for category, pattern, flags in patterns:
        if re.search(pattern, particular, flags):
            return category
    return EventCategory.CORPORATE_ACTION


# ---------------------------------------------------------------------------
# Event type classification (interim, final, special, Q1, Q3, etc.)
# ---------------------------------------------------------------------------

_EVENT_TYPE_PATTERNS_TC = [
    ("INTERIM",        r"中期業績|中期息|中期",      0),
    ("FINAL",          r"末期業績|末期息|末期",      0),
    ("FIRST_INTERIM",  r"第一期中期業績|第一季業績", 0),
    ("SECOND_INTERIM", r"第二期中期業績|第二季業績", 0),
    ("THIRD_INTERIM",  r"第三期中期業績|第三季業績", 0),
    ("SPECIAL",        r"特別業績|特別股息",         0),
]

_EVENT_TYPE_PATTERNS_EN = [
    # Order matters: more specific patterns (Q1/Q2/Q3, "Interim 1/2/3") before generic "Interim".
    ("FIRST_INTERIM",  r"Q1|Interim 1|First Interim",  re.IGNORECASE),
    ("SECOND_INTERIM", r"Q2|Interim 2|Second Interim", re.IGNORECASE),
    ("THIRD_INTERIM",  r"Q3|Interim 3|Third Interim",  re.IGNORECASE),
    ("INTERIM",        r"Interim",                     re.IGNORECASE),
    ("FINAL",          r"Final",                       re.IGNORECASE),
    ("SPECIAL",        r"Special",                     re.IGNORECASE),
]


def _classify_event_type(event_name: str, lang: str) -> str:
    """Return the event type (INTERIM, FINAL, SPECIAL, Q1, Q2, Q3)."""
    patterns = _EVENT_TYPE_PATTERNS_EN if lang == "en" else _EVENT_TYPE_PATTERNS_TC
    for etype, pattern, flags in patterns:
        if re.search(pattern, event_name, flags):
            return etype
    return "ORDINARY"


# ---------------------------------------------------------------------------
# Cash dividend parsing
# ---------------------------------------------------------------------------

# Currency names -> ISO 4217 code.
_CURRENCY_MAP: dict[str, str] = {
    "USD": "USD",
    "US$": "USD",
    "HKD": "HKD",
    "HK$": "HKD",
    "RMB": "CNY",
    "CNY": "CNY",
    "CNH": "CNY",
    "GBP": "GBP",
    "STERLING": "GBP",
    "SGD": "SGD",
    "AUD": "AUD",
    "EUR": "EUR",
    "JPY": "JPY",
    "港元": "HKD",
    "美元": "USD",
    "英鎊": "GBP",
    "人民幣": "CNY",
    "新加坡元": "SGD",
}

_CCYS = "|".join(sorted(_CURRENCY_MAP.keys(), key=len, reverse=True))
_CCYS_RE = re.compile(_CCYS)

# All three patterns must be compiled once at module load.
_AMOUNT_RE_TC = re.compile(
    rf"(?P<ccy>{_CCYS})\s*(?P<amount>[\d.]+)"
)
_HKD_EQUIV_RE_TC = re.compile(
    r"約相等於\s*(?P<hkd_amount>[\d.]+)\s*(?P<hkd_ccy>港元)"
)
_ELECT_RE_TC = re.compile(
    r"可選擇(?:以)?(?P<ccies>[^)]+?)(?:\)|,|$)"
)

_AMOUNT_RE_EN = re.compile(
    r"(?P<ccy>USD|HKD|CNY|GBP|SGD|EUR|AUD|JPY|US\$|HK\$)\s*(?P<amount>[\d.]+)"
)
_HKD_EQUIV_RE_EN = re.compile(
    r"approx\.\s*(?P<hkd_ccy>HKD)\s*(?P<hkd_amount>[\d.]+)"
)
_ELECT_RE_EN = re.compile(
    r"can choose\s*(?P<ccies>[^)]+?)(?:\)|,|$)"
)


class ParsedDividend:
    """Structured cash dividend data extracted from a particular cell."""
    __slots__ = (
        "primary_amount", "currency_primary",
        "hkd_equiv_amount", "currency_options",
        "electable_currencies", "is_special", "dividend_type",
    )

    def __init__(
        self,
        primary_amount: float | None = None,
        currency_primary: str | None = None,
        hkd_equiv_amount: float | None = None,
        currency_options: list[str] | None = None,
        electable_currencies: list[str] | None = None,
        is_special: bool = False,
        dividend_type: str = "REGULAR",
    ):
        self.primary_amount     = primary_amount
        self.currency_primary    = currency_primary
        self.hkd_equiv_amount   = hkd_equiv_amount
        self.currency_options    = currency_options or []
        self.electable_currencies = electable_currencies or []
        self.is_special         = is_special
        self.dividend_type      = dividend_type


def _normalize_currency(word: str) -> str | None:
    """Map a raw currency word/phrase to an ISO 4217 code."""
    return _CURRENCY_MAP.get(word.strip(), None)


def _parse_currencies(text: str) -> list[str]:
    """Extract all currency codes appearing in ``text``."""
    found: list[str] = []
    seen: set[str] = set()
    for m in _CCYS_RE.finditer(text):
        code = _normalize_currency(m.group())
        if code and code not in seen:
            seen.add(code)
            found.append(code)
    return found


def _parse_dividend_en(particular: str) -> ParsedDividend | None:
    """Parse an English-language particular cell for cash dividend data."""
    p = ParsedDividend()

    # Detect special dividend.
    if re.search(r"^(Special Dividend|SD)\s*[:：]|\bSpecial Dividend\b", particular, re.IGNORECASE):
        p.is_special = True
        p.dividend_type = "SPECIAL"

    # Primary amount + currency.
    # English text on AAStocks is unusual: e.g. "D :USD 0.1000 (with STERLING and HKD option)"
    # or "SD :USD 0.2100 (Equivalent to approximately HKD 1.6394, ...)" for Special Dividend.
    m = re.search(
        r"(?:Dividend|D|SD|Special Dividend)\s*[:：]\s*"
        r"(?P<ccy>USD|HKD|CNY|GBP|SGD|EUR|AUD|JPY|RMB|US\$|HK\$)\s*(?P<amount>[\d.]+)",
        particular, re.IGNORECASE,
    )
    if not m:
        return None
    # Map RMB -> CNY (ISO 4217).
    ccy = m.group("ccy").upper()
    if ccy == "RMB":
        ccy = "CNY"
    p.currency_primary = ccy
    try:
        p.primary_amount = float(m.group("amount"))
    except ValueError:
        p.primary_amount = None

    # HKD equivalent: "Equivalent to approximately HKD 3.522942" or "approx. HKD 0.783972"
    hm = re.search(
        r"(?:Equivalent to approximately|approx\.)\s*HKD\s*(?P<hkd_amount>[\d.]+)",
        particular, re.IGNORECASE,
    )
    if hm:
        try:
            p.hkd_equiv_amount = float(hm.group("hkd_amount"))
        except ValueError:
            pass

    # All currency codes appearing anywhere in the cell.
    p.currency_options = _parse_currencies(particular)

    # Electable currencies: "with STERLING and HKD option" -> all listed currencies.
    # The pattern matches anything between "with" and "option".
    elect_m = re.search(
        r"with\s+(?P<ccies>.*?)\s+option",
        particular, re.IGNORECASE,
    )
    if elect_m:
        elect_ccys = _parse_currencies(elect_m.group("ccies"))
        p.electable_currencies = [c for c in elect_ccys if c != p.currency_primary]

    return p


def _parse_dividend_tc(particular: str) -> ParsedDividend | None:
    """Parse a Traditional Chinese-language particular cell for cash dividend data."""
    p = ParsedDividend()

    # Detect special dividend.
    if "特別股息" in particular:
        p.is_special = True
        p.dividend_type = "SPECIAL"

    # Primary amount + currency (美元, 港元, 人民幣, 英鎊).
    m = re.search(
        r"(?P<ccy>美元|港元|人民幣|英鎊)\s*(?P<amount>[\d.]+)",
        particular
    )
    if not m:
        return None
    ccy_raw = m.group("ccy")
    ccy_code = _normalize_currency(ccy_raw)
    if not ccy_code:
        return None
    p.currency_primary = ccy_code
    try:
        p.primary_amount = float(m.group("amount"))
    except ValueError:
        pass

    # HKD equivalent.
    hm = re.search(r"約相等於\s*(?P<hkd_amount>[\d.]+)\s*港元", particular)
    if hm:
        try:
            p.hkd_equiv_amount = float(hm.group("hkd_amount"))
        except ValueError:
            pass

    # All currency codes appearing anywhere in the cell.
    p.currency_options = _parse_currencies(particular)

    # Electable = currencies listed in "可選擇..." clause.
    elect_m = re.search(r"可選擇(?:以)?(?P<ccies>[^)]+?)(?:\)|,|$)", particular)
    if elect_m:
        elect_ccys = _parse_currencies(elect_m.group("ccies"))
        p.electable_currencies = [c for c in elect_ccys if c != p.currency_primary]

    return p


def _translate_event_name(event: str, particular: str) -> str:
    """Attempt a rough English translation of the Chinese event name."""
    translations = [
        (r"末期業績", "Final Results"),
        (r"中期業績", "Interim Results"),
        (r"第一季業績", "Q1 Results"),
        (r"第一期中期業績", "First Interim Results"),
        (r"第二季業績", "Q2 Results"),
        (r"第二期中期業績", "Second Interim Results"),
        (r"第三季業績", "Q3 Results"),
        (r"第三期中期業績", "Third Interim Results"),
        (r"特別業績", "Special Results"),
        (r"特別股息", "Special Dividend"),
        (r"末期息", "Final Dividend"),
        (r"中期息", "Interim Dividend"),
    ]
    for pattern, en in translations:
        if re.search(pattern, event):
            return en
    # Fallback: strip common prefixes.
    stripped = re.sub(r"^(末期業績|中期業績|第一季業績|第一期中期業績|第二季業績|第二期中期業績|第三季業績|第三期中期業績|特別業績)\s*", "", event)
    return stripped if stripped else event


def _translate_particular_tc(particular: str) -> str:
    """Rough English translation of the Chinese particular cell text."""
    # Replace currency names.
    text = particular
    replacements = [
        ("美元", "USD"),
        ("港元", "HKD"),
        ("英鎊", "GBP"),
        ("人民幣", "CNY"),
        ("約相等於", "approx."),
        ("可選擇", "can choose"),
        ("可選擇以", "can choose"),
        ("更改為", "changed to"),
        ("根據", "per"),
        ("股息", "Dividend"),
        ("特別股息", "Special Dividend"),
        ("無派息", "No Dividend"),
        ("紅股", "Bonus Shares"),
        ("供股", "Rights Issue"),
        ("股份拆細", "Stock Split"),
        ("實物分派", "In Specie Distribution"),
        ("優先發售", "Preferential Offering"),
    ]
    for zh, en in replacements:
        text = text.replace(zh, en)
    return text


# ---------------------------------------------------------------------------
# Main transform function
# ---------------------------------------------------------------------------

def transform_rows(rows: list[dict], symbol: str) -> list[dict]:
    """Transform raw parsed rows into structured Step-1 output.

    One output row is produced per input row.  For cash dividend rows,
    all multi-currency amounts are captured as named columns.

    Parameters
    ----------
    rows : list[dict]
        Output of ``parse_dividend_html()``.
    symbol : str
        Stock symbol (used for context in error messages).

    Returns
    -------
    list[dict]
        Transformed rows with the columns defined in OUTPUT_COLUMNS.
    """
    out: list[dict] = []
    lang = rows[0].get("_lang", "en") if rows else "en"

    for row in rows:
        particular = row.get("particular", "")
        event     = row.get("event", "")
        category  = _classify_event(particular, lang)
        event_type = _classify_event_type(event, lang)

        out_row: dict = {
            "symbol":            symbol,
            "announce_date":    row.get("announce_date", ""),
            "year_ended":       row.get("year_ended", ""),
            "event_name_en":     _translate_event_name(event, particular) if lang == "tc" else event,
            "event_name_zh":    event,
            "event_category":   category,
            "event_type":       event_type,
            "particular_zh":    particular if lang == "tc" else "",
            "particular_en":    _translate_particular_tc(particular) if lang == "tc" else particular,
            "dividend_type":    "",
            "amount_primary":   "",
            "currency_primary": "",
            "amount_hkd_equiv": "",
            "currency_options": "[]",
            "electable_currencies": "[]",
            "is_special":       "",
            "ex_date":          row.get("ex_date", ""),
            "book_close":       row.get("book_close", ""),
            "payable_date":     row.get("payable_date", ""),
        }

        if category == EventCategory.DIVIDEND:
            parser = _parse_dividend_en if lang == "en" else _parse_dividend_tc
            pd = parser(particular)
            if pd:
                out_row.update({
                    "dividend_type":         pd.dividend_type,
                    "amount_primary":        str(pd.primary_amount) if pd.primary_amount is not None else "",
                    "currency_primary":     pd.currency_primary or "",
                    "amount_hkd_equiv":      str(pd.hkd_equiv_amount) if pd.hkd_equiv_amount is not None else "",
                    "currency_options":      json.dumps(sorted(set(pd.currency_options)), separators=(",", ":")),
                    "electable_currencies": json.dumps(sorted(set(pd.electable_currencies)), separators=(",", ":")),
                    "is_special":            "true" if pd.is_special else "false",
                })

        out.append(out_row)

    return out


# Public column list so scrape_dividend.py can introspect it.
transform_rows.OUTPUT_COLUMNS = [
    "symbol",
    "announce_date",
    "year_ended",
    "event_name_en",
    "event_name_zh",
    "event_category",
    "event_type",
    "particular_zh",
    "particular_en",
    "dividend_type",
    "amount_primary",
    "currency_primary",
    "amount_hkd_equiv",
    "currency_options",
    "electable_currencies",
    "is_special",
    "ex_date",
    "book_close",
    "payable_date",
]
