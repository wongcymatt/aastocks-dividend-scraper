# AAStocks Dividend Scraper

A small Python tool that scrapes the dividend history of Hong Kong–listed
stocks from [AAStocks](https://www.aastocks.com) and saves one CSV per
stock.

The scraper targets the **mobile Traditional Chinese** dividend page:

```
https://m.aastocks.com/tc/stocks/analysis/dividend.aspx?symbol={SYMBOL}
```

It hits that URL once per symbol with a polite `requests` GET (no headless
browser) and parses the embedded dividend table out of the static HTML
response. A desktop URL is also supported as a fallback.

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

Then run:

```bash
python scrape_dividend.py
```

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

### One-off run

```bash
python scrape_dividend.py --symbol 01114
python scrape_dividend.py --symbol 00005 --symbol 00700
```

### Switch to the desktop URL

```bash
python scrape_dividend.py --url-template desktop
```

### Adjust the politeness delay

```bash
python scrape_dividend.py --delay-min 3 --delay-max 6
```

## Output schema

Each CSV has the following columns:

| Column                | Example                | Notes                                         |
|-----------------------|------------------------|-----------------------------------------------|
| `symbol`              | `01114`                | Added by the scraper.                         |
| `announce_date`       | `2025-08-22`           | ISO date.                                     |
| `announce_date_raw`   | `2025/08/22`           | Original `yyyy/mm/dd` from the page.          |
| `year_ended`          | `2025-12`              | ISO year-month.                               |
| `year_ended_raw`      | `2025/12`              | Original.                                     |
| `event`               | `中期業績`              | Interim / Final / Special Interim, etc.       |
| `particular`          | `股息：港元 0.8000`     | Dividend amount, may be `無派息` (no dividend).|
| `type`                | `現金`                  | Cash, scrip, or `-` for no-dividend rows.     |
| `ex_date`             | `2025-09-04`           | ISO date.                                     |
| `ex_date_raw`         | `2025/09/04`           | Original.                                     |
| `book_close`          | `2025/09/08-2025/09/09`| May be a date range. Kept as text.            |
| `payable_date`        | `2025-09-26`           | ISO date.                                     |
| `payable_date_raw`    | `2025/09/26`           | Original.                                     |

CSVs are written with a UTF-8 BOM (`utf-8-sig`) so that Traditional
Chinese characters display correctly when opened directly in Excel.

## How it works

1. For each symbol, GET the dividend page with a mobile `User-Agent` and
   a `Referer` set to the same URL.
2. AAStocks returns the full dividend history table inside the static
   HTML — no JavaScript execution needed.
3. `parse_dividend.py` finds the `<table class="cnhk-cf tblM …">` whose
   first row contains the header marker `公佈日期`, then normalizes each
   row to a dict with ISO-formatted dates and a `*_raw` twin.
4. Results are written one CSV per symbol.

## Legal & ethical notice

AAStocks' [terms of service](https://www.aastocks.com/tc/stocks/aboutus/disclaimer.aspx)
restrict automated scraping and commercial reuse of their data. This
tool is intended for **personal research only**. Respect the built-in
rate limiting (1.5–3.5 s between requests) and **do not redistribute**
the raw scraped data. If you need a sustainable data feed, contact
AAStocks for a licensed data product.

## Limitations

- Scrapes the public dividend history page. Member-only / paywalled
  data is not accessible.
- The page may change its HTML structure at any time; if the parser
  starts returning `no_table_on_page` for symbols that previously
  worked, update `parse_dividend.py`.
- The script trusts whatever dates and amounts the page displays. If
  AAStocks shows a placeholder (`-`) or an empty cell, the CSV records
  an empty string.
