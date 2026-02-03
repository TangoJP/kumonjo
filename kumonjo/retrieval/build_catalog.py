"""
Build a single consolidated catalog from all raw/J/statsField JSON files.

Uses same extraction path and cleaning as tansaku/data_processing_01_retrieve_table_list.ipynb:
- TABLE_INF from GET_STATS_LIST -> DATALIST_INF -> TABLE_INF (notebook: pd.DataFrame(response['GET_STATS_LIST']['DATALIST_INF']['TABLE_INF']))
- Cleaning: clean_list_of_tables (notebook clean_statsDataId_table)
MCP discovery uses catalog_full for efficient lookups.
"""

import json
import logging
import re
from datetime import date
from pathlib import Path

import pandas as pd

from kumonjo.config import get_data_dirs
from kumonjo.processing.clean_list import clean_list_of_tables

logger = logging.getLogger(__name__)

# Raw filename: {year}_statsDataIds_from_statsField_{stats_field}.json
_RAW_PATTERN = re.compile(r"^(\d{4})_statsDataIds_from_statsField_(.+)\.json$")


def _table_inf_to_list(response: dict) -> list[dict]:
    """
    Extract TABLE_INF from getStatsList response (same path as notebook).
    Notebook: pd.DataFrame(response['GET_STATS_LIST']['DATALIST_INF']['TABLE_INF']).
    TABLE_INF can be a single dict or a list; normalize to list of dicts.
    """
    datalist = (response.get("GET_STATS_LIST") or {}).get("DATALIST_INF") or {}
    table_inf = datalist.get("TABLE_INF")
    if table_inf is None:
        return []
    if isinstance(table_inf, dict):
        return [table_inf]
    if isinstance(table_inf, list):
        return [t for t in table_inf if isinstance(t, dict)]
    return []


def build_consolidated_catalog(
    lang: str = "J",
    raw_dir: Path | str | None = None,
    processed_dir: Path | str | None = None,
    output_format: str = "parquet",
    run_date: str | None = None,
) -> pd.DataFrame:
    """
    Parse all JSON files under raw/{lang}/statsField/, clean and concatenate,
    then save a single catalog to processed/{lang}/catalog_full.{parquet|csv}.
    Discovery (list_available_years, load_catalog, search_catalog) uses this
    for efficient lookups when present.
    Returns the consolidated DataFrame; empty if no raw JSONs found.
    """
    dirs = get_data_dirs()
    raw_base = Path(raw_dir) if raw_dir else dirs["raw"]
    processed_base = Path(processed_dir) if processed_dir else dirs["processed"]
    raw_list_dir = raw_base / lang / "statsField"
    out_dir = processed_base / lang

    if not raw_list_dir.exists():
        logger.warning("Raw statsField directory not found: %s", raw_list_dir)
        return pd.DataFrame()

    if run_date is None:
        run_date = date.today().strftime("%Y%m%d")

    all_dfs: list[pd.DataFrame] = []

    for p in sorted(raw_list_dir.iterdir()):
        if not p.is_file() or not p.suffix.lower() == ".json":
            continue
        m = _RAW_PATTERN.match(p.name)
        if not m:
            continue
        year, stats_field = m.group(1), m.group(2)
        try:
            with open(p, encoding="utf-8") as f:
                response = json.load(f)
        except Exception as e:
            logger.warning("Skip %s: %s", p.name, e)
            continue

        table_list = _table_inf_to_list(response)
        if not table_list:
            continue

        df = pd.DataFrame(table_list)
        df["surveyYears"] = year
        df["statsField"] = stats_field
        df = clean_list_of_tables(df, run_date=run_date)
        all_dfs.append(df)

    if not all_dfs:
        logger.warning("No catalog rows from %s", raw_list_dir)
        return pd.DataFrame()

    combined = pd.concat(all_dfs, axis=0, ignore_index=True)

    # Parquet requires consistent column types; normalize object columns to string
    if output_format == "parquet":
        for col in combined.columns:
            if combined[col].dtype == object:
                combined[col] = combined[col].apply(
                    lambda x: "" if pd.isna(x) else (x.get("$") if isinstance(x, dict) else str(x))
                )

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"catalog_full.{output_format}"
    if output_format == "parquet":
        # Smaller row groups improve predicate pushdown (e.g. filter by year/statsField)
        combined.to_parquet(out_path, index=False, row_group_size=50_000)
    else:
        combined.to_csv(out_path, index=False)
    logger.info("Saved consolidated catalog to %s (%d rows)", out_path, len(combined))

    return combined
