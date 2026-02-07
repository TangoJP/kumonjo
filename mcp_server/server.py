#!/usr/bin/env python3
"""
MCP server for Kumonjo: discover datasets and retrieve/process e-Stat tables.
Run from project root: python mcp_server/server.py
Or: python -m mcp_server.server
Uses stdio transport by default (for Claude Desktop).
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

# Project root = parent of mcp_server/
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

try:
    from mcp.server import FastMCP
except ImportError as e:
    print(f"ERROR: Failed to import FastMCP: {e}", file=sys.stderr)
    print("Please ensure mcp package is installed: pip install 'mcp[cli]'", file=sys.stderr)
    sys.exit(1)

from kumonjo import get_api_key, get_data_dirs, fetch_table as fetch_table_internal
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

# Maximum response size in bytes (to prevent Claude message length issues)
# Roughly 50KB of JSON - conservative limit to prevent Claude message length issues
_MAX_RESPONSE_SIZE_BYTES = 50_000
_MAX_RESULT_ROWS = 500  # Maximum rows to return in results (reduced from 1000)


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

mcp = FastMCP("Kumonjo")

# Canonical list so list_available_tools and docs stay in sync
_TOOLS_META = [
    ("list_categories", "List available years and category codes (大分類). Start here to see what's searchable."),
    ("list_subcategories", "List all category/subcategory pairs (大分類・小分類) from official definitions."),
    ("list_category_codes", "List category codes and table counts for a specific year."),
    ("find_multi_year_tables", "Find tables that exist across multiple years (for time-series analysis)."),
    ("list_years", "List years that have searchable tables."),
    ("search_tables", "Search for tables by year/category/keyword. Returns table_ids to use with fetch_table."),
    ("get_table_info", "Get table metadata (survey frequency, dates). Does NOT return data rows."),
    ("fetch_table", "Fetch actual table data (columns + rows). Use table_id from search_tables."),
    ("analyze", "Analyze data from fetch_table: summary, filter, aggregate, time_series, top_bottom."),
]


@mcp.tool()
def list_available_tools() -> dict:
    """
    List all tools provided by this server.
    Workflow: search_tables (find table_ids) → fetch_table (get data) → analyze (run analysis).
    """
    return {
        "tools": [{"name": n, "description": d} for n, d in _TOOLS_META],
        "message": "search_tables で表を検索 → fetch_table でデータ取得 → analyze で分析。",
    }


@mcp.tool()
def list_categories(
    lang: str = "J",
    year: str | None = None,
    include_subcategories: bool = False,
) -> dict:
    """
    List available years and optionally category codes for a specific year. Start here to understand what's searchable.
    Use for: '何年分のデータがある？', '2024年のカテゴリ一覧', 'what categories can I search?'

    Args:
        lang: Language code. J=Japanese (default), E=English.
        year: If provided, also returns category_codes (大分類) with table counts for that year.
        include_subcategories: If True, includes full category/subcategory hierarchy.

    Returns: years (list), table_counts (per year), and optionally category_codes, subcategories.
    """
    return _log_tool_call("list_categories", lambda: _catalog_overview(lang=lang, year=year, include_stats_areas=include_subcategories))


@mcp.tool()
def list_subcategories() -> dict:
    """
    List all category and subcategory pairs (大分類・小分類) from official e-Stat definitions.
    Use for: 'どんな統計分野がある？', 'show me all categories', 'what topics are available?'

    Returns: List of categories, each with code, name, and nested subcategories.
    Note: This is the official hierarchy, not filtered by what's actually in the local catalog.
    """
    return _log_tool_call("list_subcategories", _list_stats_areas)


@mcp.tool()
def list_category_codes(
    year: str = "2024",
    lang: str = "J",
    include_names: bool = True,
) -> dict:
    """
    List category codes (大分類コード) available for a specific year, with table counts.
    Use for: '2024年にはどのカテゴリがある？', 'what categories have data in 2023?'

    Args:
        year: Year to check (e.g., "2024").
        lang: Language code. J=Japanese (default), E=English.
        include_names: If True, includes human-readable category names.

    Returns: List of {category_code, table_count, category_name} for the specified year.
    Example: category_code="02" is 人口・世帯 (Population/Households).
    """
    return _log_tool_call("list_category_codes", lambda: _list_stats_fields_for_year(year=year, lang=lang, include_names=include_names))


@mcp.tool()
def find_multi_year_tables(
    year_start: str | None = None,
    year_end: str | None = None,
    lang: str = "J",
    min_years: int = 2,
    limit: int = 50,
) -> dict:
    """
    Find tables that exist across multiple years (useful for time-series analysis).
    Use for: '複数年にわたる統計', '毎年ある統計', 'tables available from 2020 to 2024'

    Args:
        year_start: Start of year range (optional).
        year_end: End of year range (optional).
        lang: Language code. J=Japanese (default), E=English.
        min_years: Only include tables appearing in at least this many years (default 2).
        limit: Max results to return (default 50).

    Returns: List of {statistics_name, years, year_count} for tables spanning multiple years.
    """
    return _log_tool_call("find_multi_year_tables", lambda: _time_series_discovery(year_start=year_start, year_end=year_end, lang=lang, min_years=min_years, limit=limit))


@mcp.tool()
def list_years(lang: str = "J") -> dict:
    """
    List years that have searchable tables in the local catalog.
    Use for: '何年のデータがある？', 'what years are available?'

    Args:
        lang: Language code. J=Japanese (default), E=English.

    Returns: List of years (sorted) with table counts per year.
    Note: Only years with downloaded catalog data are listed.
    """
    return _log_tool_call("list_years", lambda: _list_available_years(lang=lang))


@mcp.tool()
def search_tables(
    year: str = "2024",
    lang: str = "J",
    category_code: str | None = None,
    keyword: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """
    Search for statistical tables matching your criteria. Returns table_ids to use with fetch_table.
    Use for: '2024年の雇用統計', '人口に関するデータ', 'employment statistics'

    Args:
        year: Year to search (e.g., "2024").
        lang: Language code. J=Japanese (default), E=English.
        category_code: Filter by category (e.g., "02"=人口・世帯, "03"=労働・賃金). Use list_category_codes to see options.
        keyword: Search term matched against table name, category, government org (e.g., "雇用", "人口").
        limit: Max results (default 20).

    Returns: List of tables with {table_id, statistics_name, main_category, sub_category, gov_org}.
    Next step: Use table_id with fetch_table to get actual data.
    """
    return _log_tool_call("search_tables", lambda: search_catalog(year=year, lang=lang, stats_field=category_code, keyword=keyword, limit=limit))


@mcp.tool()
def get_table_info(
    table_id: str,
    year: str = "2024",
    lang: str = "J",
    use_api_fallback: bool = True,
) -> dict:
    """
    Get metadata about a table (survey frequency, dates). Does NOT return actual data rows.
    Use for: 'この統計は月次？年次？', 'when was this table last updated?'

    Args:
        table_id: Table ID from search_tables (e.g., "0002111847").
        year: Year context for the table.
        lang: Language code. J=Japanese (default), E=English.
        use_api_fallback: If True and not in local catalog, fetches from e-Stat API.

    Returns: {survey_frequency, last_updated, data_period, statistics_name, gov_org}.
    Note: For actual data (columns, rows), use fetch_table instead.
    """
    def _do() -> dict:
        out = _get_metadata_catalog(stats_data_id=table_id.strip(), year=year, lang=lang)
        if out.get("timeout"):
            return out
        # If catalog has at least one of the key fields, consider it found
        if out.get("survey_frequency") is not None or out.get("last_updated") is not None or out.get("data_period") is not None:
            return out
        if not use_api_fallback or "該当するデータセットがカタログにありません" not in (out.get("message") or ""):
            return out
        try:
            app_id = get_api_key()
            api_meta = _fetch_meta_api(app_id=app_id, stats_data_id=table_id.strip(), year=year, lang=lang)
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

    return _log_tool_call("get_table_info", _do)


@mcp.tool()
def fetch_table(
    table_id: str,
    year: str = "2024",
    lang: str = "J",
    output_format: str = "parquet",
    save_to_disk: bool = False,
    max_rows: int = 2000,
) -> dict:
    """
    Fetch actual table data (columns and rows) from e-Stat. This is the main data retrieval tool.
    Use for: 'このテーブルのデータを取得', 'get the employment data', 'fetch table 0002111847'

    Args:
        table_id: Table ID from search_tables (e.g., "0002111847").
        year: Year of the data.
        lang: Language code. J=Japanese (default), E=English.
        output_format: "parquet" or "csv" (only used when save_to_disk=True).
        save_to_disk: If True, saves to disk and returns file path. If False (default), returns data directly.
        max_rows: Max rows to return in response (default 2000). Full row_count is always provided.

    Returns: {ok, columns, rows, row_count, truncated} when save_to_disk=False.
    Next step: Pass columns and rows to analyze() for summary, filter, aggregate, etc.
    """
    def _do() -> dict:
        try:
            app_id = get_api_key()
        except ValueError as e:
            return {"ok": False, "error": str(e), "path": None, "rows": 0}
        try:
            df = fetch_table_internal(
                app_id=app_id,
                stats_data_id=table_id.strip(),
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
            path = dirs["processed"] / lang / "statsDataId" / f"{year}_statsDataId_{table_id.strip()}.{output_format}"
            return {"ok": True, "path": str(path), "row_count": n, "error": None}
        # In-memory: return columns and rows (capped) for Claude to use
        cap = max(0, max_rows)
        sample = df.head(cap) if cap else df
        # Convert to JSON-serializable: use list of dicts; handle non-scalar values
        rows = []
        for _, r in sample.iterrows():
            rows.append({k: _json_val(v) for k, v in r.items()})
        return {
            "ok": True,
            "row_count": n,
            "columns": list(df.columns),
            "rows": rows,
            "truncated": n > cap if cap else False,
            "error": None,
        }

    return _log_tool_call("fetch_table", _do)


def _truncate_result(result: dict, max_size_bytes: int = _MAX_RESPONSE_SIZE_BYTES, max_rows: int = _MAX_RESULT_ROWS) -> dict:
    """Truncate result if it's too large, preserving structure.
    
    First truncates by row count, then checks size and truncates further if needed.
    """
    warnings = result.get("warnings", [])
    truncated = False
    
    # First pass: Truncate by row count (proactive truncation)
    if "result" in result:
        result_data = result["result"]
        
        # Handle different result structures - truncate BEFORE size check
        if "rows" in result_data and isinstance(result_data["rows"], list):
            original_count = len(result_data["rows"])
            if original_count > max_rows:
                result_data["rows"] = result_data["rows"][:max_rows]
                truncated = True
                warnings.append(
                    f"Result truncated to {max_rows} rows (original: {original_count:,} rows) "
                    f"to prevent message length issues."
                )
        
        if "groups" in result_data and isinstance(result_data["groups"], list):
            original_count = len(result_data["groups"])
            if original_count > max_rows:
                result_data["groups"] = result_data["groups"][:max_rows]
                truncated = True
                warnings.append(
                    f"Result truncated to {max_rows} groups (original: {original_count:,} groups) "
                    f"to prevent message length issues."
                )
        
        if "points" in result_data and isinstance(result_data["points"], list):
            original_count = len(result_data["points"])
            if original_count > max_rows:
                result_data["points"] = result_data["points"][:max_rows]
                truncated = True
                warnings.append(
                    f"Result truncated to {max_rows} points (original: {original_count:,} points) "
                    f"to prevent message length issues."
                )
    
    result["warnings"] = warnings
    
    # Second pass: Check size and truncate further if still too large
    result_str = json.dumps(result, ensure_ascii=False)
    result_size = len(result_str.encode("utf-8"))
    
    if result_size > max_size_bytes:
        # Still too large after row truncation - need more aggressive truncation
        # Estimate bytes per row and reduce further
        if "result" in result:
            result_data = result["result"]
            
            if "rows" in result_data and isinstance(result_data["rows"], list) and len(result_data["rows"]) > 0:
                # Estimate bytes per row
                sample_row = json.dumps(result_data["rows"][0], ensure_ascii=False)
                bytes_per_row = len(sample_row.encode("utf-8"))
                target_rows = max(10, int(max_size_bytes * 0.8 / bytes_per_row))  # Use 80% of limit
                
                if len(result_data["rows"]) > target_rows:
                    original_count = len(result_data["rows"])
                    result_data["rows"] = result_data["rows"][:target_rows]
                    warnings.append(
                        f"Result still too large after initial truncation. "
                        f"Further reduced to {target_rows} rows (original: {original_count:,} rows)."
                    )
            
            if "groups" in result_data and isinstance(result_data["groups"], list) and len(result_data["groups"]) > 0:
                sample_group = json.dumps(result_data["groups"][0], ensure_ascii=False)
                bytes_per_group = len(sample_group.encode("utf-8"))
                target_groups = max(10, int(max_size_bytes * 0.8 / bytes_per_group))
                
                if len(result_data["groups"]) > target_groups:
                    original_count = len(result_data["groups"])
                    result_data["groups"] = result_data["groups"][:target_groups]
                    warnings.append(
                        f"Result still too large after initial truncation. "
                        f"Further reduced to {target_groups} groups (original: {original_count:,} groups)."
                    )
            
            if "points" in result_data and isinstance(result_data["points"], list) and len(result_data["points"]) > 0:
                sample_point = json.dumps(result_data["points"][0], ensure_ascii=False)
                bytes_per_point = len(sample_point.encode("utf-8"))
                target_points = max(10, int(max_size_bytes * 0.8 / bytes_per_point))
                
                if len(result_data["points"]) > target_points:
                    original_count = len(result_data["points"])
                    result_data["points"] = result_data["points"][:target_points]
                    warnings.append(
                        f"Result still too large after initial truncation. "
                        f"Further reduced to {target_points} points (original: {original_count:,} points)."
                    )
        
        # Final size check
        result_str = json.dumps(result, ensure_ascii=False)
        result_size = len(result_str.encode("utf-8"))
        
        if result_size > max_size_bytes:
            warnings.append(
                f"Warning: Result is very large ({result_size:,} bytes) even after truncation. "
                f"Consider using filters or aggregation to reduce data size."
            )
    
    result["warnings"] = warnings
    
    # Final validation: ensure result can be serialized to JSON
    try:
        json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        _logger.error(f"_truncate_result: Failed to serialize result: {e}")
        # Return a minimal error result
        return {
            "type": result.get("type", "unknown"),
            "result": {},
            "meta": result.get("meta", {}),
            "warnings": warnings + [f"Error serializing result: {str(e)}"],
        }
    
    return result


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
    Analyze data returned by fetch_table. Supports summary stats, filtering, aggregation, and more.
    Use for: '合計を出して', 'filter by region', 'top 10 prefectures', 'trend over time'

    Args:
        columns: Column names from fetch_table response.
        rows: Row data from fetch_table response.
        analysis_type: One of: "summary", "filter", "aggregate", "time_series", "top_bottom".
        value_column: Column containing numeric values (default "value").
        filter_column: Column to filter on (for "filter" type).
        filter_value: Single value to match (for "filter" type).
        filter_values: List of values to match (for "filter" type).
        group_by: Columns to group by (for "aggregate" type).
        agg: Aggregation function: "sum", "mean", "count" (for "aggregate" type).
        time_column: Column for time axis (for "time_series" type, auto-detected if not set).
        n: Number of results (for "top_bottom" type, default 10).
        order: "top" or "bottom" (for "top_bottom" type).

    Returns: {type, result, meta, warnings} with analysis results.
    Large results are automatically truncated to prevent message length issues.
    """
    def _do() -> dict:
        # Check input size and log progress
        input_rows = len(rows)
        _logger.info(f"analyze: Processing {input_rows:,} rows, {len(columns)} columns")
        _logger.info(f"analyze: Analysis type: {analysis_type}")
        
        if input_rows > 5000:
            _logger.warning(f"analyze: Large dataset detected ({input_rows:,} rows) - this may take time")
        
        # Run analysis (it will build DataFrame internally)
        result = run_analysis(
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
        
        # Truncate if too large (proactive truncation)
        result = _truncate_result(result)
        
        # Add metadata about processing
        if "meta" not in result:
            result["meta"] = {}
        result["meta"]["input_rows"] = input_rows
        
        # Check final size and log
        result_size_bytes = len(json.dumps(result, ensure_ascii=False).encode("utf-8"))
        _logger.info(f"analyze: Analysis complete. Result size: {result_size_bytes:,} bytes")
        
        # Log result structure for debugging
        if "result" in result:
            result_data = result["result"]
            if "rows" in result_data:
                _logger.info(f"analyze: Result contains {len(result_data['rows'])} rows")
            if "groups" in result_data:
                _logger.info(f"analyze: Result contains {len(result_data['groups'])} groups")
            if "points" in result_data:
                _logger.info(f"analyze: Result contains {len(result_data['points'])} points")
        
        # Final safety check - if still too large, add warning
        if result_size_bytes > _MAX_RESPONSE_SIZE_BYTES:
            if "warnings" not in result:
                result["warnings"] = []
            result["warnings"].append(
                f"Warning: Result size ({result_size_bytes:,} bytes) exceeds recommended limit. "
                f"Some data may have been truncated. Consider using filters or aggregation."
            )
            _logger.warning(f"analyze: Result still exceeds size limit after truncation: {result_size_bytes:,} bytes")
        elif result_size_bytes > _MAX_RESPONSE_SIZE_BYTES * 0.8:
            if "warnings" not in result:
                result["warnings"] = []
            result["warnings"].append(
                f"Note: Result is large ({result_size_bytes:,} bytes). "
                f"Consider using filters or aggregation to reduce size."
            )
        
        return result

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


async def main() -> None:
    """Run the MCP server using stdio transport (for Claude Desktop)."""
    try:
        _logger.info("Starting Kumonjo MCP server...")
        # Use async stdio transport (same as tuber-zukan)
        await mcp.run_stdio_async()
    except KeyboardInterrupt:
        _logger.info("Server stopped by user")
    except Exception as e:
        _logger.exception("Fatal error in MCP server: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _logger.info("Server stopped by user.")
    except Exception as e:
        _logger.error(f"Server error: {e}", exc_info=True)
        sys.exit(1)
