"""Fetch list of tables (statsDataIds) by statsField and year; save raw + processed catalog."""

import json
import logging
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from kumonjo.api.client import EstatAPIError, get_stats_list
from kumonjo.processing.clean_list import clean_list_of_tables

logger = logging.getLogger(__name__)


def _table_inf_to_list(response: dict) -> list:
    """TABLE_INF can be a single dict or a list; normalize to list."""
    table_inf = (
        response.get("GET_STATS_LIST", {})
        .get("DATALIST_INF", {})
        .get("TABLE_INF", [])
    )
    if isinstance(table_inf, dict):
        return [table_inf]
    return table_inf if table_inf else []


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
    from kumonjo.config import get_data_dirs

    dirs = get_data_dirs()
    raw = Path(output_dir_raw) if output_dir_raw else dirs["raw"]
    processed = Path(output_dir_processed) if output_dir_processed else dirs["processed"]
    raw_list = raw / lang / "statsField"
    processed_list = processed / lang / "listOfStatsFields"

    if run_date is None:
        run_date = date.today().strftime("%Y%m%d")

    all_dfs = []
    for stats_field in stats_fields:
        logger.info("Retrieving tables for statsField=%s year=%s", stats_field, year)
        try:
            response = get_stats_list(
                app_id=app_id,
                stats_field=stats_field,
                survey_years=year,
                lang=lang,
            )
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

        number = (
            response.get("GET_STATS_LIST", {})
            .get("DATALIST_INF", {})
            .get("NUMBER", 0)
        )
        if number == 0:
            logger.info(
                "正常に終了しました。 statsField=%s: NUMBER=0 (該当データなし、response not saved)",
                stats_field,
            )
            continue

        # Save raw JSON
        raw_list.mkdir(parents=True, exist_ok=True)
        raw_path = raw_list / f"{year}_statsDataIds_from_statsField_{stats_field}.json"
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(response, f, ensure_ascii=False, indent=2)
        logger.info(
            "正常に終了しました。 statsField=%s: NUMBER=%s (response saved to %s)",
            stats_field,
            number,
            raw_path,
        )

        table_list = _table_inf_to_list(response)
        if not table_list:
            continue
        df = pd.DataFrame(table_list)
        df["retrieved_at"] = datetime.now()
        df["statsField"] = stats_field
        df["surveyYears"] = year
        all_dfs.append(df)

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
    else:
        logger.info("No catalog data to save")

    return df_result
