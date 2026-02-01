#!/usr/bin/env python3
"""Fetch table data for statsDataIds in the catalog. Uses ESTAT_APP_ID from .env."""

import argparse
import logging
import sys
from pathlib import Path

# Ensure project root is on path when running scripts/
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

import pandas as pd

from kumonjo import get_api_key, get_data_dirs, fetch_table

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Fetch table data for statsDataIds")
    parser.add_argument("--year", default="2024", help="Survey year")
    parser.add_argument("--lang", default="J", help="Language")
    parser.add_argument("--statsField", default="07", help="Filter catalog by statsField (e.g. 07 for 企業・家計・経済)")
    parser.add_argument("--statsDataId", default=None, help="If set, fetch only this statsDataId; else all in catalog for --statsField")
    parser.add_argument("--format", choices=["csv", "parquet"], default="parquet", help="Output format")
    args = parser.parse_args()

    dirs = get_data_dirs()
    catalog_path = dirs["processed"] / args.lang / "listOfStatsFields" / f"{args.year}_list_of_statsDataIds.csv"
    if not catalog_path.exists():
        logger.error("Catalog not found: %s. Run scripts/run_list_tables.py first.", catalog_path)
        sys.exit(1)

    df_catalog = pd.read_csv(catalog_path, dtype="object", header=0)
    df_catalog = df_catalog[df_catalog["statsField"] == args.statsField]
    ids = sorted(df_catalog["statsDataId"].unique().tolist())

    if args.statsDataId:
        ids = [args.statsDataId]

    app_id = get_api_key()
    ok = 0
    for sid in ids:
        try:
            fetch_table(
                app_id=app_id,
                stats_data_id=sid,
                year=args.year,
                lang=args.lang,
                output_format=args.format,
                save_to_disk=True,
            )
            ok += 1
        except Exception as e:
            logger.warning("Fetch failed for statsDataId=%s: %s", sid, e)
    logger.info("Fetched %d / %d tables", ok, len(ids))


if __name__ == "__main__":
    main()
