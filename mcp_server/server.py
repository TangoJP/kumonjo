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
    instructions="Tools for discovering and retrieving Japanese government statistics (e-Stat). Discovery uses catalog_full.parquet when present. Prefer catalog_overview for lookup: years available, dataset count per year, and stats_fields (with dataset_count) for a given year in one call. For any search or breakdown (e.g. '財務省のデータ', '2024年 人口・世帯', 'how many datasets per category?'), use discover_datasets(year, stats_field, keyword) — it is fast; for breakdown-by-stats_field use catalog_overview(year=Y) which returns stats_fields with counts. Do not use catalog_aggregate (not exposed). Use retrieve_and_process to fetch table data for a statsDataId. Other tools (list_available_years, list_stats_fields_for_year, list_stats_areas) are optional alternatives to catalog_overview.",
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
    from kumonjo.discovery.catalog import catalog_overview as _catalog_overview

    return _log_tool_call("catalog_overview", lambda: _catalog_overview(lang=lang, year=year, include_stats_areas=include_stats_areas))


@mcp.tool()
def list_stats_areas() -> dict:
    """
    List all stats areas (大分類・小分類) from the official statsfield.csv.
    Call when the user asks 'どの統計分野がある？' or 'list all stats areas'.
    Returns stats_areas (code, name, sub_categories) and message. Does not read the catalog.
    """
    from kumonjo.discovery.catalog import list_stats_areas as _list_stats_areas

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
    from kumonjo.discovery.catalog import list_stats_fields_for_year as _list_stats_fields_for_year

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
    from kumonjo.discovery.catalog import time_series_discovery as _time_series_discovery

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
    from kumonjo.discovery.catalog import list_available_years as _list_available_years

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
    from kumonjo.discovery.catalog import search_catalog

    return _log_tool_call("discover_datasets", lambda: search_catalog(year=year, lang=lang, stats_field=stats_field, keyword=keyword, limit=limit))


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
    from kumonjo import get_api_key, get_data_dirs, fetch_table

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
