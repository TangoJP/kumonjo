#!/usr/bin/env python3
"""
MCP server for Kumonjo: discover datasets and retrieve/process e-Stat tables.
Run from project root: python mcp_server/server.py
Or: python -m mcp_server.server
Uses stdio transport by default (for Claude Desktop).
"""

import sys
from pathlib import Path

# Project root = parent of mcp_server/
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "Kumonjo",
    instructions="Tools for discovering and retrieving Japanese government statistics (e-Stat). Discovery uses catalog_full.parquet when present. Prefer catalog_overview for lookup: years available, dataset counts, stats fields per year, and optional stats areas (one call). Use discover_datasets to search datasets by year/stats_field/keyword; use retrieve_and_process to fetch table data for a statsDataId. Other tools (list_available_years, list_stats_fields_for_year, list_stats_areas) are optional alternatives to catalog_overview.",
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

    return _catalog_overview(lang=lang, year=year, include_stats_areas=include_stats_areas)


@mcp.tool()
def list_stats_areas() -> dict:
    """
    List all stats areas (大分類・小分類) from the official statsfield.csv.
    Call when the user asks 'どの統計分野がある？' or 'list all stats areas'.
    Returns stats_areas (code, name, sub_categories) and message. Does not read the catalog.
    """
    from kumonjo.discovery.catalog import list_stats_areas as _list_stats_areas

    return _list_stats_areas()


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

    return _list_stats_fields_for_year(year=year, lang=lang, include_names=include_names)


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

    return _list_available_years(lang=lang)


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

    return search_catalog(
        year=year,
        lang=lang,
        stats_field=stats_field,
        keyword=keyword,
        limit=limit,
    )


@mcp.tool()
def retrieve_and_process(
    stats_data_id: str,
    year: str = "2024",
    lang: str = "J",
    output_format: str = "parquet",
) -> dict:
    """
    Fetch and process one e-Stat table by statsDataId. Saves raw JSON and processed table (parquet/csv).
    stats_data_id: e.g. 0002111847 (from discover_datasets).
    year: survey year.
    lang: language code (J = Japanese).
    output_format: parquet or csv.
    Returns path to the processed file, row count, and status. Requires ESTAT_APP_ID in .env.
    """
    from kumonjo import get_api_key, get_data_dirs, fetch_table

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
        )
    except Exception as e:
        return {"ok": False, "error": str(e), "path": None, "rows": 0}

    if df.empty:
        return {"ok": False, "error": "No data extracted", "path": None, "rows": 0}

    dirs = get_data_dirs()
    path = dirs["processed"] / lang / "statsDataId" / f"{year}_statsDataId_{stats_data_id.strip()}.{output_format}"
    return {
        "ok": True,
        "path": str(path),
        "rows": len(df),
        "error": None,
    }


def main() -> None:
    # stdio is the default for Claude Desktop
    mcp.run()


if __name__ == "__main__":
    main()
