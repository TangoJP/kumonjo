"""Fetch list of tables (statsDataIds) by statsField and year; save raw + processed catalog."""

import json
import logging
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from kumonjo.api.client import EstatAPIError, get_stats_list
from kumonjo.config import get_data_dirs
from kumonjo.processing.clean_list import clean_list_of_tables
from kumonjo.retrieval.build_catalog import build_consolidated_catalog

logger = logging.getLogger(__name__)


def _table_inf_to_list(response: dict) -> list:
    """
    Extract TABLE_INF from getStatsList response; normalize to list.
    Path: GET_STATS_LIST -> DATALIST_INF -> TABLE_INF.
    TABLE_INF can be a single dict (one table) or a list; missing/None -> [].
    """
    datalist = response.get("GET_STATS_LIST", {}) or {}
    datalist = datalist.get("DATALIST_INF", {}) or {}
    table_inf = datalist.get("TABLE_INF")
    if table_inf is None:
        return []
    if isinstance(table_inf, dict):
        return [table_inf]
    if isinstance(table_inf, list):
        return [t for t in table_inf if isinstance(t, dict)]
    return []


def fetch_list_of_tables(
    app_id: str,
    year: str,
    stats_fields: list[str],
    lang: str = "J",
    output_dir_raw: Path | str | None = None,
    output_dir_processed: Path | str | None = None,
    run_date: str | None = None,
) -> pd.DataFrame:
    """
    For each statsField, call getStatsList; concatenate TABLE_INF, clean, and save.
    Returns the combined catalog DataFrame. Saves raw JSON per statsField and
    one CSV under processed/{lang}/listOfStatsFields/{year}_list_of_statsDataIds.csv.
    """
    dirs = get_data_dirs()
    raw = Path(output_dir_raw) if output_dir_raw else dirs["raw"]
    processed = Path(output_dir_processed) if output_dir_processed else dirs["processed"]
    raw_list = raw / lang / "statsField"
    processed_list = processed / lang / "listOfStatsFields"

    if run_date is None:
        run_date = date.today().strftime("%Y%m%d")

    page_limit = 10000  # e-Stat may cap per-request; paginate to get all
    all_dfs = []
    for stats_field in stats_fields:
        logger.info("Retrieving tables for statsField=%s year=%s", stats_field, year)
        try:
            all_tables: list[dict] = []
            total_expected = 0
            start_position = 1
            first_response = None

            while True:
                response = get_stats_list(
                    app_id=app_id,
                    stats_field=stats_field,
                    survey_years=year,
                    lang=lang,
                    start_position=start_position,
                    limit=page_limit,
                )
                if first_response is None:
                    first_response = response

                datalist = (response.get("GET_STATS_LIST") or {}).get("DATALIST_INF") or {}
                total_expected = datalist.get("NUMBER", 0)
                if total_expected == 0:
                    break

                page_tables = _table_inf_to_list(response)
                all_tables.extend(page_tables)

                if len(page_tables) < page_limit or len(all_tables) >= total_expected:
                    break
                start_position = len(all_tables) + 1
                logger.info(
                    "statsField=%s: fetched %s/%s, requesting next page from %s",
                    stats_field,
                    len(all_tables),
                    total_expected,
                    start_position,
                )

            if total_expected == 0:
                logger.info(
                    "正常に終了しました。 statsField=%s: NUMBER=0 (該当データなし、response not saved)",
                    stats_field,
                )
                continue

            if len(all_tables) < total_expected:
                logger.warning(
                    "statsField=%s year=%s: got %s items, NUMBER=%s (API may cap per request)",
                    stats_field,
                    year,
                    len(all_tables),
                    total_expected,
                )

            # Build merged response so saved JSON has full TABLE_INF
            merged = dict(first_response) if first_response else {}
            gl = merged.setdefault("GET_STATS_LIST", {})
            di = gl.setdefault("DATALIST_INF", {})
            di["TABLE_INF"] = all_tables
            di["NUMBER"] = len(all_tables)
            if "RESULT_INF" in di:
                di["RESULT_INF"] = {"FROM_NUMBER": 1, "TO_NUMBER": len(all_tables)}

            # Save raw JSON (full catalog for this stats_field + year)
            raw_list.mkdir(parents=True, exist_ok=True)
            raw_path = raw_list / f"{year}_statsDataIds_from_statsField_{stats_field}.json"
            with open(raw_path, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
            logger.info(
                "正常に終了しました。 statsField=%s: %s tables (saved to %s)",
                stats_field,
                len(all_tables),
                raw_path,
            )

            if not all_tables:
                continue
            df = pd.DataFrame(all_tables)
            df["retrieved_at"] = datetime.now()
            df["statsField"] = stats_field
            df["surveyYears"] = year
            all_dfs.append(df)

        except EstatAPIError as e:
            logger.error(
                "e-Stat API error for statsField=%s: STATUS=%s — %s (response not saved)",
                stats_field,
                e.status,
                e.message,
            )
            continue
        except Exception as e:
            logger.error("getStatsList failed for statsField=%s: %s", stats_field, e)
            continue

    if not all_dfs:
        df_result = pd.DataFrame()
    else:
        df_result = pd.concat(all_dfs, axis=0).reset_index(drop=True)
        df_result = clean_list_of_tables(df_result, run_date=run_date)

    if not df_result.empty:
        processed_list.mkdir(parents=True, exist_ok=True)
        out_path = processed_list / f"{year}_list_of_statsDataIds.csv"
        df_result.to_csv(out_path, index=False)
        logger.info("Saved catalog to %s", out_path)

    # Update consolidated catalog for efficient MCP lookups
    try:
        build_consolidated_catalog(lang=lang, output_format="parquet")
    except Exception as e:
        logger.debug("Could not update consolidated catalog: %s", e)

    if df_result.empty:
        logger.info("No catalog data to save")

    return df_result
