#!/usr/bin/env python3
"""Build consolidated catalog from all raw/J/statsField JSON files. MCP discovery uses it for efficient lookups."""

import argparse
import logging
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

from kumonjo.retrieval.build_catalog import build_consolidated_catalog

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Build consolidated catalog from raw statsField JSONs")
    parser.add_argument("--lang", default="J", help="Language")
    parser.add_argument("--format", choices=["parquet", "csv"], default="parquet", help="Output format")
    args = parser.parse_args()

    df = build_consolidated_catalog(lang=args.lang, output_format=args.format)
    if df.empty:
        logger.warning("No data; ensure data/raw/%s/statsField/*.json exist (run run_list_tables.py first).", args.lang)
        sys.exit(1)
    logger.info("Done. Catalog: %d rows", len(df))


if __name__ == "__main__":
    main()
