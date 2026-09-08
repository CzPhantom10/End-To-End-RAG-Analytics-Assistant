"""Download the example dataset.

The project ships with the classic "Sample - Superstore" retail dataset (9,994
order lines, 2014-2017). It is not generated - it is fetched from a public
GitHub mirror of the Tableau sample workbook data.

Usage:
    python data/fetch_data.py
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent

SOURCES: dict[str, dict[str, str]] = {
    "superstore.csv": {
        "url": "https://raw.githubusercontent.com/sumit0072/Superstore-Data-Analysis/main/Sample%20-%20Superstore.csv",
        "description": "Sample - Superstore: 9,994 US retail order lines with Sales, Profit, "
        "Quantity, Discount across Region, Category, Segment and Customer (2014-2017).",
    },
    "supermarket_sales.csv": {
        "url": "https://raw.githubusercontent.com/plotly/datasets/master/supermarket_Sales.csv",
        "description": "Supermarket sales: 1,000 transactions across 3 branches with unit price, "
        "quantity, tax, gross income and customer ratings.",
    },
}


def fetch(name: str, spec: dict[str, str]) -> bool:
    target = HERE / name
    if target.exists() and target.stat().st_size > 1000:
        print(f"[skip]  {name} already present ({target.stat().st_size:,} bytes)")
        return True
    print(f"[fetch] {name} <- {spec['url']}")
    try:
        with urllib.request.urlopen(spec["url"], timeout=60) as response:
            payload = response.read()
    except Exception as exc:  # noqa: BLE001
        print(f"[fail]  {name}: {exc}")
        return False
    target.write_bytes(payload)
    print(f"[ok]    {name} ({len(payload):,} bytes) - {spec['description']}")
    return True


def main() -> int:
    results = [fetch(name, spec) for name, spec in SOURCES.items()]
    if not all(results):
        print("\nSome downloads failed. Check your internet connection and retry.")
        return 1
    print("\nAll example datasets are in place.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
