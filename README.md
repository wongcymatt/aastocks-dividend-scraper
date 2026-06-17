# AAStocks Dividend Scraper

A small Python tool that scrapes the dividend history of Hong Kong–listed
stocks from [AAStocks](https://www.aastocks.com) and saves one CSV per
stock.

Two languages are supported, both via plain `requests` GETs (no headless
browser needed). The default is `en` (English).

| `--lang` | URL |
|---|---|
| `en` (default) | `https://m.aastocks.com/en/stocks/analysis/dividend.aspx?symbol={SYMBOL}` |
| `tc` | `https://m.aastocks.com/tc/stocks/analysis/dividend.aspx?symbol={SYMBOL}` |

Both return the full dividend history table embedded in the static HTML
response. The English page uses a shorter `Accept-Language: en-US,en;q=0.9`
header to force the English body.

A desktop URL is also available via `--layout desktop` for either language.

## Installation

Requires Python 3.10+.

```bash
cd "/Users/cymatt_/Rivermap/Web scraping AA"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

Edit `stocks.txt` and put one HK stock symbol per line (5-digit, zero-padded).
The default file lists five large-cap test symbols:

```
00005   # HSBC
00001   # CK Hutchison
00016   # Sun Hung Kai Properties
00388   # HK Exchanges
00700   # Tencent
```

### Default: English with Step 1 transform

```bash
python scrape_dividend.py
```

### Traditional Chinese page

```bash
python scrape_dividend.py --lang tc
```

### One-off run

```bash
python scrape_dividend.py --symbol 01114
python scrape_dividend.py --lang en --symbol 00005 --symbol 00700
```

### Skip the transform (raw scraped output only)

```bash
python scrape_dividend.py --lang en --symbol 00005 --no-transform
```

### Switch to the desktop URL

```bash
python scrape_dividend.py --layout desktop
```

### Adjust the politeness delay

```bash
python scrape_dividend.py --delay-min 3 --delay-max 6
```

### Output

The script prints one line per symbol and writes one CSV per symbol to
`output/`:

```
output/
├── dividend_00005.csv
├── dividend_00001.csv
├── dividend_00016.csv
├── dividend_00388.csv
└── dividend_00700.csv
```

## Output schema

The default output (with `--transform`, which is on by default) has these
columns. Use `--no-transform` to get the original raw 13-column output.

| Column | Example | Notes |
|---|---|---|
| `symbol` | `01114` | Added by the scraper. |
| `announce_date` | `2025-08-22` | ISO date (announcement date). |
| `year_ended` | `2025-12` | ISO year-month of the reporting period. |
| `event_name` | `Interim` (en) / `中期業績` (tc) | The event name **in the source language** of the scrape. |
| `event_name_translated` | `Interim Results` | English translation of `event_name` (TC source only). Empty when the source was already English. |
| `event_category` | `DIVIDEND` | High-level bucket. One of: `DIVIDEND`, `NO_DIVIDEND`, `BONUS_SHARES`, `RIGHTS_ISSUE`, `STOCK_SPLIT`, `INSPECIE`, `PREFERRED_OFFERING`, `CORPORATE_ACTION` (catch-all). |
| `event_type` | `INTERIM` | Granular classification. One of: `INTERIM`, `FINAL`, `FIRST_INTERIM` (Q1), `SECOND_INTERIM` (Q2), `THIRD_INTERIM` (Q3), `SPECIAL`, `ORDINARY` (catch-all). |
| `particular` | `D :USD 0.1000 ...` (en) / `股息：美元 0.1000 ...` (tc) | Original particular-cell text from the scraped page. |
| `particular_translated` | `Dividend: USD 0.1000 ...` | English translation of `particular` (TC source only). Empty when the source was English. |
| `dividend_type` | `REGULAR` / `SPECIAL` | Empty when not a cash dividend. `SPECIAL` means the AAStocks page tagged it as `SD :` (Special Dividend) or `特別股息`. |
| `amount_primary` | `0.1000` | Primary dividend amount. |
| `currency_primary` | `USD` | ISO 4217 code of the primary amount (USD, HKD, CNY, GBP, SGD, AUD, EUR, JPY). The Chinese currency name `人民幣`/`RMB` is normalized to `CNY`. |
| `amount_hkd_equiv` | `0.783972` | The HKD equivalent listed on the page (e.g. "Equivalent to approximately HKD 0.78"). Empty if the page did not list one. |
| `all_currency_amounts` | `{"USD":0.1,"HKD":0.777722}` | JSON object of every `{currency: amount}` pair explicitly present in the cell. Always includes `amount_primary`; also includes `HKD` when `amount_hkd_equiv` is present. Empty `{}` for non-dividend rows. |
| `currency_options` | `["USD","GBP","HKD"]` | JSON array of every ISO currency code that appears in the cell, including currencies that are mentioned without an explicit amount (e.g. `GBP` in "with STERLING and HKD option"). |
| `electable_currencies` | `["GBP","HKD"]` | JSON array of currencies the shareholder can elect to receive in (i.e. everything in `currency_options` other than the primary). Empty when there's no election clause. |
| `is_special` | `true` / `false` | `true` if this row is a special dividend. |
| `ex_date` | `2025-09-04` | ISO date (ex-dividend date). |
| `book_close` | `2025/09/08-2025/09/09` | Book-close period; may be a date range or a single date. Kept as text. |
| `payable_date` | `2025-09-26` | ISO date (payable date). |

CSVs are written with a UTF-8 BOM (`utf-8-sig`) so that Chinese / English
characters display correctly when opened directly in Excel.

### How `event_category` and `event_type` are derived

- **`event_category`** is matched against the `particular` cell text. The
  most common patterns are `D :USD …` (English) / `股息：美元 …` (Chinese)
  for `DIVIDEND`, and `No Dividend` / `無派息` for `NO_DIVIDEND`. Anything
  unrecognized falls back to `CORPORATE_ACTION`.
- **`event_type`** is matched against the `event` cell. `Interim` /
  `中期業績` → `INTERIM`, `Final` / `末期業績` → `FINAL`. `Q1`/`Q2`/`Q3`
  and `Interim 1/2/3` map to `FIRST_INTERIM`/`SECOND_INTERIM`/
  `THIRD_INTERIM` (more specific patterns are checked first). The English
  shorthand `SD :` triggers `SPECIAL`. Anything else → `ORDINARY`.
- **`is_special`** is set independently from the category — it fires when
  the page uses `SD :` (English) or `特別股息` (Chinese) for the
  particular cell, regardless of category.

## How it works

1. For each symbol, GET the dividend page with a mobile `User-Agent` and a
   `Referer` set to the same URL.
2. AAStocks returns the full dividend history table inside the static HTML
   — no JavaScript execution needed.
3. `parse_dividend.py` finds the `<table>` whose first row contains a
   header marker (`公佈日期` for Chinese, `Announce Date` for English), then
   normalizes each row to a dict with ISO-formatted dates.
4. `transform_dividend.py` (Step 1) classifies each row into an event
   category, classifies the event type (interim/final/Q1-Q3/special), and
   for cash dividends extracts the primary amount + currency, the HKD
   equivalent, and all selectable currencies.
5. Results are written one CSV per symbol.

## Legal & ethical notice

AAStocks' [terms of service](https://www.aastocks.com/tc/stocks/aboutus/disclaimer.aspx)
restrict automated scraping and commercial reuse of their data. This
tool is intended for **personal research only**. Respect the built-in
rate limiting (1.5–3.5 s between requests) and **do not redistribute**
the raw scraped data. If you need a sustainable data feed, contact
AAStocks for a licensed data product.

## Limitations

- Scrapes the public dividend history page. Member-only / paywalled data
  is not accessible.
- The page may change its HTML structure at any time; if the parser starts
  returning `no_table_on_page` for symbols that previously worked, update
  `parse_dividend.py`.
- The script trusts whatever dates and amounts the page displays. If
  AAStocks shows a placeholder (`-`) or an empty cell, the CSV records an
  empty string.
- The Step 1 transform's regex patterns cover the most common AAStocks
  particular-cell formats but may not cover every edge case. Unrecognized
  rows fall back to `event_category = CORPORATE_ACTION` and empty amount
  columns.
