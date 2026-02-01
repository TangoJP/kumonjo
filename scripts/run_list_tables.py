#!/usr/bin/env python3
"""Fetch list of tables (catalog) for all statsFields and a given year. Uses ESTAT_APP_ID from .env."""

import argparse
import logging
import sys
from pathlib import Path

# Ensure project root is on path when running scripts/
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

import pandas as pd

from kumonjo import get_api_key, get_data_dirs, fetch_list_of_tables

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Fetch list of statsDataIds by statsField and year")
    parser.add_argument("--year", default="2024", help="Survey year")
    parser.add_argument("--lang", default="J", help="Language")
    args = parser.parse_args()

    dirs = get_data_dirs()
    statsfield_path = dirs["official"] / "statsfield.csv"
    if not statsfield_path.exists():
        print(f"Missing {statsfield_path}")
        sys.exit(1)

    df_statsfields = pd.read_csv(statsfield_path, dtype="object", header=0)
    stats_fields = sorted(df_statsfields["大分類コード"].unique().tolist())

    app_id = get_api_key()
    fetch_list_of_tables(
        app_id=app_id,
        year=args.year,
        stats_fields=stats_fields,
        lang=args.lang,
    )


if __name__ == "__main__":
    main()
