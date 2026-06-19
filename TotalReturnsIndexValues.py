"""
Fetch Total Returns Index (TRI) values for ALL NIFTY indices over a date range
and combine them into a single CSV: dates as rows, index names as columns.

Usage:
    python fetch_nifty_tri.py --start 20-Jun-2023 --end 19-Jun-2024 --out nifty_tri.csv

Notes:
- Source: https://www.niftyindices.com/Backpage.aspx/getTotalReturnIndexString
- The site is somewhat strict about headers; we mimic a browser request.
- The full index list (~100+ names) is embedded below, taken from the
  NSE/NIFTY indices master list. Edit INDEX_NAMES if you want to
  restrict to a subset (faster, fewer chances of throttling).
"""

import argparse
import csv
import json
import sys
import time
from datetime import datetime

import requests

URL = "https://www.niftyindices.com/Backpage.aspx/getTotalReturnIndexString"

HEADERS = {
    "Content-Type": "application/json; charset=UTF-8",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://www.niftyindices.com/reports/historical-data",
    "Origin": "https://www.niftyindices.com",
    "X-Requested-With": "XMLHttpRequest",
}

# Full list of index names pulled from the four reference documents.
INDEX_NAMES = [
    # Broad market
    "NIFTY 100", "NIFTY 200", "NIFTY 50", "NIFTY 500", "NIFTY INDIA FPI 150",
    "NIFTY LARGEMIDCAP 250", "NIFTY MICROCAP250", "NIFTY MIDCAP 100",
    "NIFTY MIDCAP 150", "NIFTY MIDCAP 50", "NIFTY MID SELECT",
    "NIFTY MIDSMALLCAP 400", "NIFTY MIDSMALLCAP400 50:50", "NIFTY NEXT 50",
    "NIFTY SMALLCAP 100", "NIFTY SMALLCAP 250", "NIFTY SMALLCAP 50",
    "NIFTY SMALLCAP 500", "NIFTY TOTAL MKT",
    "NIFTY500 LARGEMIDSMALL EQUAL-CAP WEIGHTED", "NIFTY500 MULTICAP 50:25:25",

    # Sectoral
    "NIFTY AUTO", "NIFTY BANK", "NIFTY CAPITAL GOODS", "NIFTY CEMENT",
    "NIFTY CHEMICALS", "NIFTY COMMERCIAL & TRANSPORT SERVICES",
    "NIFTY CONSTRUCTION", "NIFTY CONSUMER DURABLES", "NIFTY CONSUMER SERVICES",
    "NIFTY FINANCIAL SERVICES", "NIFTY FINANCIAL SERVICES 25/50",
    "NIFTY FINANCIAL SERVICES EX-BANK", "NIFTY FMCG", "NIFTY HEALTHCARE",
    "NIFTY HOSPITALS", "NIFTY HOUSING FINANCE", "NIFTY INSURANCE", "NIFTY IT",
    "NIFTY MEDIA", "NIFTY METAL", "NIFTY MIDSMALL FINANCIAL SERVICES",
    "NIFTY MIDSMALL HEALTHCARE", "NIFTY MIDSMALL IT & TELECOM", "NIFTY NBFC",
    "NIFTY OIL & GAS", "NIFTY PHARMA", "NIFTY POWER", "NIFTY PRIVATE BANK",
    "NIFTY PSU BANK", "NIFTY REALTY", "NIFTY REITS & REALTY", "NIFTY RETAIL",
    "NIFTY TELECOMMUNICATIONS", "NIFTY500 HEALTHCARE",

    # Strategy / factor
    "NIFTY 50 FUTURES TR INDEX", "NIFTY ALPHA 50", "NIFTY ALPHA LOW-VOLATILITY 30",
    "NIFTY ALPHA QUALITY LOW-VOLATILITY 30",
    "NIFTY ALPHA QUALITY VALUE LOW-VOLATILITY 30",
    "NIFTY DIVIDEND OPPS 50", "NIFTY GROWTH SECTORS 15",
    "NIFTY HIGH BETA 50", "NIFTY LOW VOLATILITY 50",
    "NIFTY MIDCAP150 MOMENTUM 50", "NIFTY MIDCAP150 QUALITY 50",
    "NIFTY MIDSMALLCAP400 MOMENTUM QUALITY 100",
    "NIFTY QUALITY LOW-VOLATILITY 30", "NIFTY SMALLCAP250 MOMENTUM QUALITY 100",
    "NIFTY SMALLCAP250 QUALITY 50", "NIFTY TOP 10 EQUAL WEIGHT",
    "NIFTY TOP 15 EQUAL WEIGHT", "NIFTY TOP 20 EQUAL WEIGHT",
    "NIFTY TOTAL MARKET MOMENTUM QUALITY 50", "NIFTY100 ALPHA 30",
    "NIFTY100 EQUAL WEIGHT", "NIFTY100 LOW VOLATILITY 30", "NIFTY100 QUALTY 30",
    "NIFTY200 ALPHA 30", "NIFTY200 MOMENTUM 30", "NIFTY200 QUALITY 30",
    "NIFTY200 VALUE 30", "NIFTY50 EQUAL WEIGHT", "NIFTY50 VALUE 20",
    "NIFTY500 EQUAL WEIGHT", "NIFTY500 FLEXICAP QUALITY 30",
    "NIFTY500 LOW VOLATILITY 50", "NIFTY500 MOMENTUM 50",
    "NIFTY500 MULTICAP MOMENTUM QUALITY 50", "NIFTY500 MULTIFACTOR MQVLV 50",
    "NIFTY500 QUALITY 50", "NIFTY500 VALUE 50",

    # Thematic
    "NIFTY CAPITAL MARKETS", "NIFTY COMMODITIES", "NIFTY CONGLOMERATE 50",
    "NIFTY CORE HOUSING", "NIFTY CPSE", "NIFTY ENERGY",
    "NIFTY EV & NEW AGE AUTOMOTIVE", "NIFTY HOUSING", "NIFTY INDIA CONSUMPTION",
    "NIFTY INDIA CORPORATE GROUP INDEX - ADITYA BIRLA GROUP",
    "NIFTY INDIA CORPORATE GROUP INDEX - MAHINDRA GROUP",
    "NIFTY INDIA CORPORATE GROUP INDEX - TATA GROUP",
    "NIFTY INDIA CORPORATE GROUP INDEX - TATA GROUP 25% CAP",
    "NIFTY INDIA DEFENCE", "NIFTY IND DIGITAL",
    "NIFTY INDIA INFRASTRUCTURE & LOGISTICS", "NIFTY INDIA INTERNET",
    "NIFTY INDIA MFG", "NIFTY INDIA NEW AGE CONSUMPTION",
    "NIFTY INDIA RAILWAYS PSU", "NIFTY INDIA SELECT 5 CORPORATE GROUPS (MAATR)",
    "NIFTY INDIA TOURISM", "NIFTY INFRASTRUCTURE", "NIFTY IPO",
    "NIFTY MIDCAP LIQUID 15", "NIFTY MIDSMALL INDIA CONSUMPTION", "NIFTY MNC",
    "NIFTY MOBILITY", "NIFTY NON-CYCLICAL CONSUMER", "NIFTY PSE",
    "NIFTY REITS & INVITS", "NIFTY RURAL", "NIFTY SERVICES SECTOR",
    "NIFTY SHARIAH 25", "NIFTY SMALL FINANCE BANKS & MICROFINANCE INSTITUTIONS",
    "NIFTY SME EMERGE", "NIFTY SUGAR & ETHANOL",
    "NIFTY TRANSPORTATION & LOGISTICS", "NIFTY WAVES", "NIFTY100 ENHANCED ESG",
    "NIFTY100 ESG", "NIFTY100 ESG SECTOR LEADERS", "NIFTY100 LIQUID 15",
    "NIFTY50 SHARIAH", "NIFTY500 MULTICAP INDIA MANUFACTURING 50:30:20",
    "NIFTY500 MULTICAP INFRASTRUCTURE 50:30:20", "NIFTY500 SHARIAH",
]


def fetch_index_tri(index_name: str, start_date: str, end_date: str,
                     session: requests.Session, retries: int = 3,
                     pause: float = 1.0):
    """
    Fetch TRI history for one index between start_date and end_date.
    Dates must be in 'DD-Mon-YYYY' format, e.g. '20-Jun-2023'.

    Returns a dict {date_str: tri_value} or None on failure.
    """
    cinfo = (
        "{'name':'" + index_name + "','startDate':'" + start_date +
        "','endDate':'" + end_date + "','indexName':'" + index_name + "'}"
    )
    payload = {"cinfo": cinfo}

    for attempt in range(1, retries + 1):
        try:
            resp = session.post(URL, headers=HEADERS, json=payload, timeout=20)
            resp.raise_for_status()
            outer = resp.json()
            # The API wraps the real payload as a JSON string inside "d"
            inner = outer.get("d")
            if not inner:
                return {}
            records = json.loads(inner)
            result = {}
            for rec in records:
                date_str = rec.get("Date")
                tri_str = rec.get("TotalReturnsIndex")
                if date_str and tri_str and tri_str != "-":
                    result[date_str] = tri_str
            return result
        except Exception as exc:
            print(f"  [warn] {index_name}: attempt {attempt} failed ({exc})",
                  file=sys.stderr)
            time.sleep(pause * attempt)
    print(f"  [error] {index_name}: giving up after {retries} attempts",
          file=sys.stderr)
    return None


def normalize_date(d: str) -> str:
    """Convert '19 Jun 2024' -> '2024-06-19' for clean sorting in CSV."""
    return datetime.strptime(d, "%d %b %Y").strftime("%Y-%m-%d")


def main():
    parser = argparse.ArgumentParser(description="Fetch all NIFTY TRI indices into one CSV")
    parser.add_argument("--start", required=True, help="Start date, e.g. 20-Jun-2023")
    parser.add_argument("--end", required=True, help="End date, e.g. 19-Jun-2024")
    parser.add_argument("--out", default="nifty_tri.csv", help="Output CSV path")
    parser.add_argument("--delay", type=float, default=0.5,
                         help="Seconds to sleep between requests (be polite to the API)")
    parser.add_argument("--indices", nargs="*", default=None,
                         help="Optional subset of index names to fetch (space-separated, "
                              "quote multi-word names). Defaults to the full list.")
    args = parser.parse_args()

    names = args.indices if args.indices else INDEX_NAMES
    print(f"Fetching {len(names)} indices from {args.start} to {args.end} ...")

    session = requests.Session()

    # date -> {index_name: value}
    data = {}

    for i, name in enumerate(names, 1):
        print(f"[{i}/{len(names)}] {name}")
        series = fetch_index_tri(name, args.start, args.end, session)
        if series is None:
            continue
        for raw_date, value in series.items():
            try:
                iso_date = normalize_date(raw_date)
            except ValueError:
                iso_date = raw_date  # fallback, keep as-is
            data.setdefault(iso_date, {})[name] = value
        time.sleep(args.delay)

    if not data:
        print("No data fetched. Exiting without writing CSV.", file=sys.stderr)
        sys.exit(1)

    all_dates = sorted(data.keys())
    fieldnames = ["Date"] + names

    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for d in all_dates:
            row = {"Date": d}
            row.update(data[d])
            writer.writerow(row)

    print(f"\nDone. Wrote {len(all_dates)} rows x {len(names)} index columns to {args.out}")


if __name__ == "__main__":
    main()