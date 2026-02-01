"""Fetch one table (statsDataId); optionally save raw JSON + processed DataFrame (parquet/csv)."""

import json
import logging
from pathlib import Path

import pandas as pd

from kumonjo.api.client import EstatAPIError, get_stats_data
from kumonjo.processing.parse_response import (
    extract_data_from_response,
    reorder_df_columns,
)

logger = logging.getLogger(__name__)


def fetch_table(
    app_id: str,
    stats_data_id: str,
    year: str,
    lang: str = "J",
    output_dir_raw: Path | str | None = None,
    output_dir_processed: Path | str | None = None,
    output_format: str = "parquet",
    save_to_disk: bool = False,
) -> pd.DataFrame:
    """
    Call getStatsData for one statsDataId; optionally save raw JSON and processed table.
    When save_to_disk is False (default), only fetch and process in memory; no files written.
    Returns the merged DataFrame; empty if fetch or parse failed.
    """
    from kumonjo.config import get_data_dirs

    dirs = get_data_dirs()
    raw = Path(output_dir_raw) if output_dir_raw else dirs["raw"]
    processed = Path(output_dir_processed) if output_dir_processed else dirs["processed"]
    raw_dir = raw / lang / "statsDataId"
    processed_dir = processed / lang / "statsDataId"

    if output_format not in ("csv", "parquet"):
        raise ValueError("output_format must be 'csv' or 'parquet'")

    if save_to_disk:
        raw_dir.mkdir(parents=True, exist_ok=True)
        processed_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Fetching statsDataId=%s year=%s", stats_data_id, year)
    try:
        response = get_stats_data(
            app_id=app_id,
            stats_data_id=stats_data_id,
            survey_years=year,
            lang=lang,
        )
    except EstatAPIError as e:
        logger.error(
            "e-Stat API error for statsDataId=%s: STATUS=%s — %s (response not saved)",
            stats_data_id,
            e.status,
            e.message,
        )
        return pd.DataFrame()
    except Exception as e:
        logger.error("getStatsData failed for statsDataId=%s: %s", stats_data_id, e)
        return pd.DataFrame()

    if save_to_disk:
        raw_path = raw_dir / f"{year}_statsDataId_{stats_data_id}.json"
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(response, f, ensure_ascii=False, indent=2)
        logger.info("正常に終了しました。 statsDataId=%s: raw response saved to %s", stats_data_id, raw_path)

    df = extract_data_from_response(response)
    if df.empty:
        logger.info("No DataFrame extracted for statsDataId=%s", stats_data_id)
        return df

    df = reorder_df_columns(df, offset=2)

    if save_to_disk:
        out_path = processed_dir / f"{year}_statsDataId_{stats_data_id}.{output_format}"
        if output_format == "parquet":
            df.to_parquet(out_path, index=False)
        else:
            df.to_csv(out_path, index=False)
        logger.info("正常に終了しました。 statsDataId=%s: table saved to %s", stats_data_id, out_path)

    return df
