#!/usr/bin/env python3
"""
MCP server for Kumonjo: discover datasets and retrieve/process e-Stat tables.
Run from project root: python mcp_server/server.py
Or: python -m mcp_server.server
Uses stdio transport by default (for Claude Desktop).
"""

import json
import logging
import sys
import time
from pathlib import Path

# Project root = parent of mcp_server/
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from mcp.server.fastmcp import FastMCP

from kumonjo import get_api_key, get_data_dirs, fetch_table
from kumonjo.analysis import run_analysis
from kumonjo.discovery.catalog import (
    catalog_overview as _catalog_overview,
    get_dataset_metadata as _get_metadata_catalog,
    list_available_years as _list_available_years,
    list_stats_areas as _list_stats_areas,
    list_stats_fields_for_year as _list_stats_fields_for_year,
    search_catalog,
    time_series_discovery as _time_series_discovery,
)
from kumonjo.retrieval.get_table import fetch_dataset_metadata as _fetch_meta_api

# Log to stderr so stdio remains clean for JSON-RPC
_logger = logging.getLogger("kumonjo.mcp")
_logger.setLevel(logging.INFO)
if not _logger.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(message)s"))
    _logger.addHandler(_h)


def _log_tool_call(tool_name: str, thunk):
    """Run thunk(), log start/end and response size. Returns thunk result."""
    _logger.info("tool=%s start", tool_name)
    start = time.perf_counter()
    try:
        result = thunk()
        elapsed = time.perf_counter() - start
        try:
            size = len(json.dumps(result, ensure_ascii=False))
        except (TypeError, ValueError):
            size = -1
        _logger.info("tool=%s end elapsed_sec=%.3f response_size=%d", tool_name, elapsed, size)
        return result
    except Exception as e:
        elapsed = time.perf_counter() - start
        _logger.exception("tool=%s error after %.3fs: %s", tool_name, elapsed, e)
        raise

mcp = FastMCP(
    "Kumonjo",
    instructions="Tools for discovering, retrieving, and analyzing Japanese government statistics (e-Stat). (1) Search for datasets: use discover_datasets(year, stats_field, keyword). (2) Fetch table contents (columns and rows): use retrieve_and_process(stats_data_id, year, lang)—do NOT use get_dataset_metadata for that (metadata only). (3) After retrieve_and_process, use analyze(columns, rows, analysis_type, ...) for summary, filter, aggregate, time_series, or top_bottom. catalog_overview for years and stats_fields; list_* are alternatives. Do not use catalog_aggregate (not exposed).",
    json_response=True,
)


@mcp.tool()
def catalog_overview(
    lang: str = "J",
    year: str | None = None,
    include_stats_areas: bool = False,
) -> dict:
    """
    Single lookup for catalog: years available, dataset count per year, and optionally stats fields for a given year or master stats areas. Use for '何年分のデータが検索できる？', '2024年の統計分野全て', or 'overview of what I can search'.
    lang: language code (J = Japanese).
    year: if set, also return stats_fields (大分類コード + dataset_count + names) for this year; if null, only years + counts.
    include_stats_areas: if True, add stats_areas (大分類・小分類 from statsfield.csv).
    Returns years, summary (dataset_count per year), optional year, stats_fields, stats_areas, and message.
    """
    return _log_tool_call("catalog_overview", lambda: _catalog_overview(lang=lang, year=year, include_stats_areas=include_stats_areas))


@mcp.tool()
def list_stats_areas() -> dict:
    """
    List all stats areas (大分類・小分類) from the official statsfield.csv.
    Call when the user asks 'どの統計分野がある？' or 'list all stats areas'.
    Returns stats_areas (code, name, sub_categories) and message. Does not read the catalog.
    """
    return _log_tool_call("list_stats_areas", _list_stats_areas)


@mcp.tool()
def list_stats_fields_for_year(
    year: str = "2024",
    lang: str = "J",
    include_names: bool = True,
) -> dict:
    """
    Return unique stats_field (大分類コード) for a given year with dataset counts. Fast: reads only that year from the catalog (predicate pushdown).
    Call when the user asks '2024年の統計分野全て出して' or 'which stats fields have data in year X'.
    year: survey year (e.g. 2024).
    lang: language code (J = Japanese).
    include_names: if True, add 大分類 names from statsfield.csv (default True).
    Returns year, lang, stats_fields (list of {stats_field, dataset_count, stats_field_name}), and message.
    """
    return _log_tool_call("list_stats_fields_for_year", lambda: _list_stats_fields_for_year(year=year, lang=lang, include_names=include_names))


@mcp.tool()
def time_series_discovery(
    year_start: str | None = None,
    year_end: str | None = None,
    lang: str = "J",
    min_years: int = 2,
    limit: int = 50,
) -> dict:
    """
    Find statistics that exist across multiple years (e.g. same statistics_name 2020–2024). Use for '複数年にわたる統計' or '毎年ある統計'.
    year_start, year_end: optional year range; only consider years in [year_start, year_end].
    min_years: include only statistics appearing in at least this many years (default 2).
    limit: max number of statistics to return (default 50).
    Returns year_start, year_end, lang, statistics (statistics_name, stat_name_code, years, year_count), message.
    """
    return _log_tool_call("time_series_discovery", lambda: _time_series_discovery(year_start=year_start, year_end=year_end, lang=lang, min_years=min_years, limit=limit))


@mcp.tool()
def list_available_years(lang: str = "J") -> dict:
    """
    List which years have a local catalog (so datasets can be discovered for those years).
    Uses the consolidated catalog (data/processed/{lang}/catalog_full.parquet) when present; does not scan JSON files.
    Call this when the user asks "何年分のデータが検索できる？" or "what years are available?".
    lang: language code (J = Japanese).
    Returns years (sorted), summary with dataset_count per year, and a short message in Japanese.
    """
    return _log_tool_call("list_available_years", lambda: _list_available_years(lang=lang))


@mcp.tool()
def discover_datasets(
    year: str = "2024",
    lang: str = "J",
    stats_field: str | None = None,
    keyword: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """
    Find datasets (statsDataIds) in the catalog that match the given criteria.
    Uses the consolidated catalog (data/processed/{lang}/catalog_full.parquet) when present; does not search JSON files.
    Use this to answer questions like "2024年の雇用統計" or "人口・世帯のデータ".
    year: survey year (e.g. 2024).
    lang: language code (J = Japanese).
    stats_field: optional statsField code (e.g. 02=人口・世帯, 03=労働・賃金, 07=企業・家計・経済).
    keyword: optional search term matched against statistics name, category, gov org (e.g. 雇用, 人口).
    limit: max number of datasets to return (default 20).
    Returns a list of datasets with statsDataId, statistics_name, main_category_name, sub_category_name, gov_org_name.
    """
    return _log_tool_call("discover_datasets", lambda: search_catalog(year=year, lang=lang, stats_field=stats_field, keyword=keyword, limit=limit))


@mcp.tool()
def get_dataset_metadata(
    stats_data_id: str,
    year: str = "2024",
    lang: str = "J",
    use_api_fallback: bool = True,
) -> dict:
    """
    Return detailed dataset metadata: survey frequency (月次/年次), last updated, data period from e-Stat.
    Tries the catalog first; if the dataset is not in the catalog and use_api_fallback is True, fetches from the e-Stat API.
    stats_data_id: e.g. 0002111847 (from discover_datasets).
    year: survey year.
    lang: language code (J = Japanese).
    use_api_fallback: if True and not in catalog, call e-Stat API for metadata (requires ESTAT_APP_ID).
    Returns survey_frequency, last_updated, data_period, statistics_name, title, gov_org_name (when available).
    """
    def _do() -> dict:
        out = _get_metadata_catalog(stats_data_id=stats_data_id.strip(), year=year, lang=lang)
        if out.get("timeout"):
            return out
        # If catalog has at least one of the key fields, consider it found
        if out.get("survey_frequency") is not None or out.get("last_updated") is not None or out.get("data_period") is not None:
            return out
        if not use_api_fallback or "該当するデータセットがカタログにありません" not in (out.get("message") or ""):
            return out
        try:
            app_id = get_api_key()
            api_meta = _fetch_meta_api(app_id=app_id, stats_data_id=stats_data_id.strip(), year=year, lang=lang)
            if api_meta.get("error"):
                out["message"] = api_meta.get("error", "API error")
                return out
            return api_meta
        except ValueError as e:
            out["message"] = str(e)
            return out
        except Exception as e:
            out["message"] = str(e)
            return out

    return _log_tool_call("get_dataset_metadata", _do)


@mcp.tool()
def retrieve_and_process(
    stats_data_id: str,
    year: str = "2024",
    lang: str = "J",
    output_format: str = "parquet",
    save_to_disk: bool = False,
    max_rows_in_response: int = 2000,
) -> dict:
    """
    Fetch and process one e-Stat table by statsDataId.
    When save_to_disk is False (default): data is returned in the response (columns, rows, row_count); nothing is written to disk.
    When save_to_disk is True: raw JSON and processed table are saved; returns path to the processed file.
    stats_data_id: e.g. 0002111847 (from discover_datasets).
    year: survey year.
    lang: language code (J = Japanese).
    output_format: parquet or csv (used only when save_to_disk is True).
    save_to_disk: if True, write to data/raw and data/processed and return path; if False, return data in response.
    max_rows_in_response: when save_to_disk is False, include at most this many rows in the response (default 2000); row_count is always the full count.
    Returns ok, row_count, and either (path when save_to_disk) or (columns, rows when not). Requires ESTAT_APP_ID in .env.
    """
    def _do() -> dict:
        try:
            app_id = get_api_key()
        except ValueError as e:
            return {"ok": False, "error": str(e), "path": None, "rows": 0}
        try:
            df = fetch_table(
                app_id=app_id,
                stats_data_id=stats_data_id.strip(),
                year=year,
                lang=lang,
                output_format=output_format,
                save_to_disk=save_to_disk,
            )
        except Exception as e:
            return {"ok": False, "error": str(e), "path": None, "rows": 0}
        if df.empty:
            return {"ok": False, "error": "No data extracted", "path": None, "rows": 0}
        n = len(df)
        if save_to_disk:
            dirs = get_data_dirs()
            path = dirs["processed"] / lang / "statsDataId" / f"{year}_statsDataId_{stats_data_id.strip()}.{output_format}"
            return {"ok": True, "path": str(path), "rows": n, "error": None}
        # In-memory: return columns and rows (capped) for Claude to use
        cap = max(0, max_rows_in_response)
        sample = df.head(cap) if cap else df
        # Convert to JSON-serializable: use list of dicts; handle non-scalar values
        rows = []
        for _, r in sample.iterrows():
            rows.append({k: _json_val(v) for k, v in r.items()})
        return {
            "ok": True,
            "path": None,
            "rows": n,
            "row_count": n,
            "columns": list(df.columns),
            "rows_sample": rows,
            "truncated": n > cap if cap else False,
            "error": None,
        }

    return _log_tool_call("retrieve_and_process", _do)


@mcp.tool()
def analyze(
    columns: list[str],
    rows: list[dict],
    analysis_type: str,
    value_column: str = "value",
    filter_column: str | None = None,
    filter_value: str | int | float | None = None,
    filter_values: list | None = None,
    group_by: list[str] | None = None,
    agg: str = "sum",
    time_column: str | None = None,
    n: int = 10,
    order: str = "top",
) -> dict:
    """
    Run basic analysis on a table (use columns and rows from retrieve_and_process).
    analysis_type: one of summary, filter, aggregate, time_series, top_bottom.
    summary: stats (count, mean, median, min, max, std, sum) on value column; use value_column to override default "value".
    filter: subset rows; set filter_column and either filter_value (single) or filter_values (list).
    aggregate: group by group_by columns and agg (sum, mean, count) the value column.
    time_series: aggregate value by time; time_column optional (inferred from names like time_name, year if not set).
    top_bottom: top n or bottom n by value; set n and order ("top" or "bottom"); optional group_by for per-group top/bottom.
    Returns type, result (fixed schema per analysis type), and optional meta, warnings.
    """
    def _do() -> dict:
        return run_analysis(
            columns=columns,
            rows=rows,
            analysis_type=analysis_type.strip().lower(),
            value_column=value_column or "value",
            filter_column=filter_column,
            filter_value=filter_value,
            filter_values=filter_values,
            group_by=group_by or [],
            agg=agg or "sum",
            time_column=time_column,
            n=max(1, min(n, 1000)) if n is not None else 10,
            order=(order or "top").strip().lower(),
        )

    return _log_tool_call("analyze", _do)


def _json_val(v) -> str | int | float | None:
    """Coerce a cell value to a JSON-serializable type."""
    if v is None:
        return None
    if isinstance(v, float) and v != v:  # NaN
        return None
    if isinstance(v, (str, int, float)):
        return v
    return str(v)


def main() -> None:
    # stdio is the default for Claude Desktop
    mcp.run()


if __name__ == "__main__":
    main()
