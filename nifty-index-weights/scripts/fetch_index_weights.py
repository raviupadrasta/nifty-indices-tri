#!/usr/bin/env python3
"""Fetch index constituent weights from niftyindices.com.

Data source: liveindexsa.niftyindices.com publishes each index's sector/stock
composition as a JSONP file (`modelDataAvailable({...}, {...})`). This script
strips the JSONP wrapper, parses the (non-standard, trailing-comma) JS object,
flattens the sector -> stock tree, and writes one dated CSV per index.

Usage:
    python fetch_index_weights.py --list                    # refresh + show available index names
    python fetch_index_weights.py "NIFTY AUTO" "NIFTY BANK"  # fetch specific indices
    python fetch_index_weights.py --file reference/indices.txt
    python fetch_index_weights.py --category "Broad Market Indices" "Sectoral Indices"

The endpoint is keyed by name and inconsistently uses either the abbreviated
`IndexTradingname` or the full `Title` from the master list (e.g. `NIFTY FIN
SERVICE` 404s but `NIFTY FINANCIAL SERVICES` works) -- both are tried before
giving up. Debt/GSec/SDL/target-maturity/money-market/hybrid indices and a
handful of derivative-based equity indices (arbitrage, leveraged/inverse)
have no stock composition to publish at all -- those are reported as
skipped, not treated as errors.
"""
import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_TYPE_URL = "https://liveindexsa.niftyindices.com/jsonfiles/IndexType.json"
SECTOR_URL_TMPL = "https://liveindexsa.niftyindices.com/jsonfiles/Sector/SectorialIndexData{name}_Sector.js"
HEADERS = {"User-Agent": "Mozilla/5.0"}
WEIGHT_SUFFIX_RE = re.compile(r"\s+[\d.]+%$")

# Endpoint publishes under a name that doesn't derive from IndexTradingname or Title
# by any general rule found so far (verified by hand, not a heuristic -- don't extend
# this by guessing, only by confirming a 200 first).
NAME_OVERRIDES = {
    "Nifty India Internet & E-Commerce": "NIFTY INDIA INTERNET",
}
TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def fetch_index_list(cache_path: Path | None = None) -> list[dict]:
    """Download the master index list and cache it for reference."""
    data = json.loads(_get(INDEX_TYPE_URL))
    if cache_path:
        cache_path.write_text(json.dumps(data, indent=2))
    return data


def _extract_first_object(text: str) -> str:
    """Pull the balanced {...} for the first argument to modelDataAvailable(...)."""
    start = text.index("{")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise ValueError("unbalanced braces in response")


def fetch_composition(name: str) -> dict | None:
    """Fetch and parse the sector/stock composition for one index name.

    Returns None if the index has no published composition (HTTP 404).
    """
    url = SECTOR_URL_TMPL.format(name=urllib.request.quote(name.upper()))
    try:
        text = _get(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    obj_text = TRAILING_COMMA_RE.sub(r"\1", _extract_first_object(text))
    return json.loads(obj_text)


def fetch_composition_for_entry(entry: dict) -> tuple[dict | None, str | None]:
    """Try IndexTradingname, Title, Title with '%' stripped, then any NAME_OVERRIDES entry.

    The endpoint drops literal '%' characters from the name rather than
    percent-encoding them (e.g. Title "...25% Cap" -> URL "...25 CAP").

    Returns (data, name_that_worked), or (None, None) if all candidates failed.
    """
    trading_name = entry["IndexTradingname"]
    candidates = [trading_name]
    title = entry.get("Title", "")
    if title and title.upper() != trading_name.upper():
        candidates.append(title)
    if "%" in title:
        stripped = " ".join(title.replace("%", "").split())
        if stripped.upper() not in (c.upper() for c in candidates):
            candidates.append(stripped)
    override = NAME_OVERRIDES.get(trading_name) or NAME_OVERRIDES.get(title)
    if override and override.upper() not in (c.upper() for c in candidates):
        candidates.append(override)

    for name in candidates:
        data = fetch_composition(name)
        if data is not None:
            return data, name
    return None, None


def _strip_weight(label: str) -> str:
    return WEIGHT_SUFFIX_RE.sub("", label).strip()


def flatten(data: dict) -> list[dict]:
    """Flatten the sector -> stock tree into one row per constituent."""
    rows = []
    for sector in data.get("groups", []):
        sector_name = _strip_weight(sector["label"])
        for stock in sector.get("groups", []):
            rows.append(
                {
                    "sector": sector_name,
                    "sector_weight": sector["weight"],
                    "symbol": _strip_weight(stock["label"]),
                    "weight": stock["weight"],
                    "as_of_date": stock.get("date", ""),
                }
            )
    return rows


def save_csv(index_name: str, rows: list[dict], data_dir: Path) -> Path:
    as_of = rows[0]["as_of_date"] if rows else "unknown"
    # as_of_date comes as DD-MM-YYYY; use it directly for a stable, sortable-ish filename
    safe_name = index_name.upper().replace(" ", "_")
    out_path = data_dir / f"{safe_name}_{as_of}.csv"
    data_dir.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["sector", "sector_weight", "symbol", "weight", "as_of_date"])
        writer.writeheader()
        writer.writerows(rows)
    return out_path


def resolve_entries(names: list[str], master: list[dict]) -> list[dict]:
    """Resolve raw name strings to master-list entries (for the Title fallback).

    Names not found in the master list (e.g. a typo, or a name from an older
    list) are passed through as-is with no fallback available.
    """
    by_trading_name = {e["IndexTradingname"].upper(): e for e in master}
    resolved = []
    for name in names:
        entry = by_trading_name.get(name.upper())
        resolved.append(entry if entry else {"IndexTradingname": name, "Title": name})
    return resolved


def run(entries: list[dict], data_dir: Path) -> None:
    seen = set()
    for entry in entries:
        trading_name = entry["IndexTradingname"]
        if trading_name in seen:
            continue  # master list has a few duplicate IndexTradingname entries
        seen.add(trading_name)

        try:
            data, used_name = fetch_composition_for_entry(entry)
        except Exception as e:
            print(f"ERROR   {trading_name}: {e}")
            continue
        if data is None:
            tried = trading_name
            if entry.get("Title") and entry["Title"].upper() != trading_name.upper():
                tried += f" / {entry['Title']}"
            print(f"SKIP    {trading_name}: no composition data published (tried: {tried})")
            continue
        rows = flatten(data)
        if not rows:
            print(f"SKIP    {trading_name}: composition data was empty")
            continue
        out_path = save_csv(trading_name, rows, data_dir)
        via = f" (via '{used_name}')" if used_name != trading_name else ""
        print(f"OK      {trading_name}: {len(rows)} constituents -> {out_path.relative_to(ROOT)}{via}")
        time.sleep(0.3)  # be polite to the endpoint


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("indices", nargs="*", help="Index trading names to fetch (e.g. 'NIFTY AUTO')")
    parser.add_argument("--file", type=Path, help="Text file with one index trading name per line")
    parser.add_argument("--category", nargs="*", help="Fetch every index in these IndexType categories (from the master list)")
    parser.add_argument("--list", action="store_true", help="Refresh reference/index_type.json and print available categories")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data", help="Output directory for CSVs")
    args = parser.parse_args()

    if args.list:
        master = fetch_index_list(ROOT / "reference" / "index_type.json")
        categories: dict[str, int] = {}
        for entry in master:
            categories[entry["IndexType"]] = categories.get(entry["IndexType"], 0) + 1
        print(f"Fetched {len(master)} indices -> reference/index_type.json")
        for cat, count in categories.items():
            print(f"  {cat}: {count}")
        return

    names: list[str] = list(args.indices)
    if args.file:
        names.extend(line.strip() for line in args.file.read_text().splitlines() if line.strip() and not line.startswith("#"))

    if not names and not args.category:
        parser.error("no indices specified: pass names, --file, --category, or --list")

    cache_path = ROOT / "reference" / "index_type.json"
    master = json.loads(cache_path.read_text()) if cache_path.exists() else fetch_index_list(cache_path)

    entries = resolve_entries(names, master)
    if args.category:
        entries.extend(e for e in master if e["IndexType"] in args.category)

    run(entries, args.data_dir)


if __name__ == "__main__":
    main()
