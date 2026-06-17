# AAStocks Dividend Scraper

A small Python tool that scrapes the dividend history of Hong Kong–listed
stocks from [AAStocks](https://www.aastocks.com) and saves one CSV per
stock.

Two languages are supported, both via plain `requests` GETs (no headless
browser needed):

| `--lang` | URL |
|---|---|
| `tc` (default) | `https://m.aastocks.com/tc/stocks/analysis/dividend.aspx?symbol={SYMBOL}` |
| `en` | `https://m.aastocks.com/en/stocks/analysis/dividend.aspx?symbol={SYMBOL}` |

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

### Default: Chinese with Step 1 transform

```bash
python scrape_dividend.py
```

### English page

```bash
python scrape_dividend.py --lang en
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
| `announce_date` | `2025-08-22` | ISO date. |
| `year_ended` | `2025-12` | ISO year-month. |
| `event_name_en` | `Interim Results` | English event name (translated for `--lang tc`). |
| `event_name_zh` | `中期業績` | Original event name. |
| `event_category` | `DIVIDEND` | One of: `DIVIDEND`, `NO_DIVIDEND`, `BONUS_SHARES`, `RIGHTS_ISSUE`, `STOCK_SPLIT`, `INSPECIE`, `PREFERRED_OFFERING`, `CORPORATE_ACTION`. |
| `event_type` | `INTERIM` | One of: `INTERIM`, `FINAL`, `FIRST_INTERIM` (Q1), `SECOND_INTERIM` (Q2), `THIRD_INTERIM` (Q3), `SPECIAL`, `ORDINARY`. |
| `particular_zh` | `股息：港元 0.8000` | Original Chinese text (empty when scraped from English page). |
| `particular_en` | `D :USD 0.1000 ...` | English text (translated for `--lang tc`). |
| `dividend_type` | `REGULAR` / `SPECIAL` | Empty when not a cash dividend. |
| `amount_primary` | `0.1000` | Primary dividend amount. |
| `currency_primary` | `USD` | ISO 4217 code (USD, HKD, CNY, GBP, …). RMB is normalized to CNY. |
| `amount_hkd_equiv` | `0.783972` | HKD-equivalent amount when listed on the page; empty otherwise. |
| `currency_options` | `["USD","GBP","HKD"]` | JSON array of all currencies mentioned in the cell. |
| `electable_currencies` | `["GBP","HKD"]` | JSON array of currencies the shareholder can elect. |
| `is_special` | `true` / `false` | Whether this is a special dividend. |
| `ex_date` | `2025-09-04` | ISO date. |
| `book_close` | `2025/09/08-2025/09/09` | Date range, kept as text. |
| `payable_date` | `2025-09-26` | ISO date. |

CSVs are written with a UTF-8 BOM (`utf-8-sig`) so that Chinese / English
characters display correctly when opened directly in Excel.

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
