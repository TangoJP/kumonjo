# Kumonjo MCP server and Claude Desktop

The Kumonjo MCP server exposes tools for searching, fetching, and analyzing Japanese government statistics (e-Stat 統計表).

## Workflow

1. **search_tables** → Find tables by year/category/keyword, get `table_id`s
2. **fetch_table** → Fetch actual data (columns + rows) using `table_id`
3. **analyze** → Run analysis on the fetched data

## Tool Overview

| Tool | Purpose |
|------|---------|
| **search_tables** | Search for tables by year, category, keyword. Returns `table_id`s. |
| **fetch_table** | Fetch table data (columns + rows). Use `table_id` from search_tables. |
| **analyze** | Analyze data: summary, filter, aggregate, time_series, top_bottom. |
| get_table_info | Get metadata (frequency, dates). Does NOT return data rows. |
| list_categories | List years and category codes. Start here to see what's searchable. |
| list_years | List years with available tables. |
| list_category_codes | List category codes for a specific year. |
| list_subcategories | List all category/subcategory pairs from official definitions. |
| find_multi_year_tables | Find tables spanning multiple years (for time-series). |
| list_available_tools | List all tools (use if unsure what's available). |

## Prerequisites

1. **Catalog** – Run `python scripts/run_list_tables.py --year 2024` (and other years), then `python scripts/run_build_catalog.py` to build `data/processed/{lang}/catalog_full.parquet`.
2. **API key** – Set `ESTAT_APP_ID` in `.env` (required for `fetch_table`).

## Run the MCP server (stdio)

From the **project root**:

```bash
python mcp_server/server.py
```

Or:

```bash
python -m mcp_server.server
```

The server uses **stdio** transport by default (for Claude Desktop).

## Add to Claude Desktop

1. Open Claude Desktop settings (e.g. **Settings → Developer → Edit config**).
2. Add the Kumonjo MCP server under `mcpServers`:

```json
{
  "mcpServers": {
    "kumonjo": {
      "command": "python",
      "args": ["/absolute/path/to/kumonjo/mcp_server/server.py"],
      "env": {
        "ESTAT_APP_ID": "your_e-stat_app_id"
      }
    }
  }
}
```

Or load from `.env` by omitting the `env` key:

```json
{
  "mcpServers": {
    "kumonjo": {
      "command": "python",
      "args": ["/absolute/path/to/kumonjo/mcp_server/server.py"]
    }
  }
}
```

3. Restart Claude Desktop. The tools **search_tables**, **fetch_table**, and **analyze** should appear.

### Troubleshooting: tools not showing

- **Fully quit and restart Claude Desktop** (quit the app, not just close the window).
- Ensure `args` points to the **absolute path** of `mcp_server/server.py`.
- If tools are reported as "not found", quit Claude Desktop completely, reopen, and start a new chat.
- Test with MCP Inspector: `uv run mcp dev mcp_server/server.py`
- Ask Claude to call **list_available_tools** to see all available tools.

### fetch_table vs get_table_info

- **fetch_table** → Returns actual data (columns, rows). Use this for data analysis.
- **get_table_info** → Returns metadata only (survey frequency, dates). Does NOT return data.

For prompts like "get the data and show me what's in it", use **fetch_table**.

## Tool Parameters

### search_tables

Search for tables matching your criteria. Returns `table_id`s to use with fetch_table.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| year | string | "2024" | Year to search. |
| lang | string | "J" | Language (J=Japanese, E=English). |
| category_code | string | null | Filter by category (e.g., "02"=人口・世帯, "03"=労働・賃金). |
| keyword | string | null | Search term matched against name, category, gov org. |
| limit | int | 20 | Max results. |

Returns: List of `{table_id, statistics_name, main_category, sub_category, gov_org}`.

### fetch_table

Fetch actual table data from e-Stat.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| table_id | string | (required) | Table ID from search_tables (e.g., "0002111847"). |
| year | string | "2024" | Year of the data. |
| lang | string | "J" | Language. |
| output_format | string | "parquet" | "parquet" or "csv" (only when save_to_disk=True). |
| save_to_disk | bool | false | If true, save to disk and return path. If false, return data in response. |
| max_rows | int | 2000 | Max rows in response. Full row_count always provided. |

**When save_to_disk=false (default):** Returns `{ok, columns, rows, row_count, truncated}`.

**When save_to_disk=true:** Returns `{ok, path, row_count}`.

Requires `ESTAT_APP_ID` in environment.

### analyze

Analyze data from fetch_table.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| columns | list | (required) | Column names from fetch_table. |
| rows | list | (required) | Row data from fetch_table. |
| analysis_type | string | (required) | "summary", "filter", "aggregate", "time_series", "top_bottom". |
| value_column | string | "value" | Column with numeric values. |
| filter_column | string | null | Column to filter on (for "filter"). |
| filter_value | any | null | Single value to match (for "filter"). |
| filter_values | list | null | List of values to match (for "filter"). |
| group_by | list | [] | Columns to group by (for "aggregate"). |
| agg | string | "sum" | Aggregation: "sum", "mean", "count" (for "aggregate"). |
| time_column | string | null | Time column (for "time_series", auto-detected if not set). |
| n | int | 10 | Number of results (for "top_bottom"). |
| order | string | "top" | "top" or "bottom" (for "top_bottom"). |

Returns: `{type, result, meta, warnings}`.

### get_table_info

Get metadata about a table (NOT actual data).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| table_id | string | (required) | Table ID from search_tables. |
| year | string | "2024" | Year context. |
| lang | string | "J" | Language. |
| use_api_fallback | bool | true | Fetch from API if not in local catalog. |

Returns: `{survey_frequency, last_updated, data_period, statistics_name, gov_org}`.

### list_categories

List available years and category codes.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| lang | string | "J" | Language. |
| year | string | null | If set, include category codes for this year. |
| include_subcategories | bool | false | Include full category/subcategory hierarchy. |

Returns: `{years, table_counts, category_codes (if year set), subcategories (if requested)}`.

### list_years

List years with searchable tables.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| lang | string | "J" | Language. |

Returns: List of years with table counts.

### list_category_codes

List category codes for a specific year.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| year | string | "2024" | Year to check. |
| lang | string | "J" | Language. |
| include_names | bool | true | Include human-readable category names. |

Returns: List of `{category_code, table_count, category_name}`.

### list_subcategories

List all category/subcategory pairs from official e-Stat definitions.

No parameters.

Returns: List of categories with codes, names, and nested subcategories.

### find_multi_year_tables

Find tables that exist across multiple years.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| year_start | string | null | Start of year range. |
| year_end | string | null | End of year range. |
| lang | string | "J" | Language. |
| min_years | int | 2 | Minimum years a table must span. |
| limit | int | 50 | Max results. |

Returns: List of `{statistics_name, years, year_count}`.

## Using MCP CLI (optional)

With [uv](https://docs.astral.sh/uv/):

- **Inspector**: `uv run mcp dev mcp_server/server.py`
- **Install**: `uv run mcp install mcp_server/server.py`
