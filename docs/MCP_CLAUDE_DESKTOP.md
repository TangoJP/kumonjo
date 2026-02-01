# Kumonjo MCP server and Claude Desktop

The Kumonjo MCP server exposes tools for discovering and retrieving Japanese government statistics (e-Stat). Discovery uses the **consolidated catalog** (`data/processed/{lang}/catalog_full.parquet`) when present.

## How Claude looks up years and related info

- **catalog_overview** (recommended) – Single lookup: years available, dataset count per year, and optionally stats fields for a given year or master stats areas (大分類・小分類). Use for "何年分のデータが検索できる？", "2024年の統計分野全て", or "overview of what I can search".
- **list_available_years** – Years that have a local catalog + dataset count per year (subset of catalog_overview).
- **list_stats_fields_for_year(year)** – Unique stats_field (大分類コード) for a year with dataset counts (subset of catalog_overview when year is set).
- **list_stats_areas** – Master list of 大分類・小分類 from statsfield.csv (subset of catalog_overview when include_stats_areas=True).
- **discover_datasets** – Search datasets by year, stats_field, keyword; returns list of statsDataIds + metadata.
- **retrieve_and_process** – Fetch and process one table by statsDataId. By default returns data in the response (no disk write); optionally save raw JSON and parquet/csv with `save_to_disk=true`.

Prefer **catalog_overview** for "what years / what stats fields / overview" in one call; use **discover_datasets** to search, and **retrieve_and_process** to fetch table data.

For "how many datasets per category?" or breakdown questions, use **discover_datasets** (targeted calls) or **catalog_overview(year=Y)** for stats_field counts — these are faster than the previous catalog_aggregate tool, which is no longer exposed.

## Prerequisites

1. **Catalog** – Run `python scripts/run_list_tables.py --year 2024` (and other years as needed), then `python scripts/run_build_catalog.py` to build `data/processed/{lang}/catalog_full.parquet`. Discovery uses this consolidated file when available.
2. **API key** – Set `ESTAT_APP_ID` in `.env` (required for `retrieve_and_process`).

## Run the MCP server (stdio)

From the **project root**:

```bash
python mcp_server/server.py
```

Or:

```bash
python -m mcp_server.server
```

The server uses **stdio** transport by default (for Claude Desktop). It will wait for JSON-RPC messages on stdin and write responses to stdout.

## Add to Claude Desktop

1. Open Claude Desktop settings (e.g. **Settings → Developer → Edit config**).
2. Add the Kumonjo MCP server under `mcpServers`. Example (adjust paths to your machine):

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

Or, if you prefer to load `.env` from the project directory, you can omit `ESTAT_APP_ID` from `env` and ensure the server is run from the project root so it finds `.env`:

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

3. Restart Claude Desktop. The tools **discover_datasets** and **retrieve_and_process** should appear.

## Using the MCP CLI (optional)

If you use [uv](https://docs.astral.sh/uv/) and install with `uv pip install -e ".[mcp]"` or `pip install "mcp[cli]"`:

- **Development / Inspector**: `uv run mcp dev mcp_server/server.py` (then connect the MCP Inspector to the URL it prints).
- **Install into Claude Desktop**: `uv run mcp install mcp_server/server.py` (may add the server to your Claude Desktop config; see `mcp install --help`).

## Tool parameters

### catalog_overview

| Parameter            | Type   | Default | Description |
|----------------------|--------|---------|-------------|
| lang                 | string | "J"     | Language (J = Japanese). |
| year                 | string | null    | If set, also return stats_fields (大分類 + counts + names) for this year. |
| include_stats_areas  | bool   | false   | If true, add stats_areas (大分類・小分類 from statsfield.csv). |

Returns `years`, `summary` (dataset_count per year), optional `year` and `stats_fields`, optional `stats_areas`, and `message`. Use for "何年分のデータが検索できる？", "2024年の統計分野全て", or overview.

### list_available_years

| Parameter | Type   | Default | Description |
|-----------|--------|---------|-------------|
| lang      | string | "J"     | Language (J = Japanese). |

Returns `years`, `lang`, `summary` (list of `{year, dataset_count}`), and `message`. Alternative to catalog_overview when only years + counts are needed.

### list_stats_fields_for_year

| Parameter     | Type   | Default | Description |
|---------------|--------|---------|-------------|
| year          | string | "2024"  | Survey year. |
| lang          | string | "J"     | Language. |
| include_names | bool   | true    | Add 大分類 names from statsfield.csv. |

Returns `year`, `lang`, `stats_fields` (list of `{stats_field, dataset_count, stats_field_name}`), and `message`. Alternative to catalog_overview(year=...) when only one year's stats fields are needed.

### list_stats_areas

No parameters. Returns `stats_areas` (code, name, sub_categories) and `message` from statsfield.csv. Alternative to catalog_overview(include_stats_areas=true) when only the master list is needed.

### discover_datasets

| Parameter     | Type   | Default | Description |
|--------------|--------|---------|-------------|
| year         | string | "2024"  | Survey year. |
| lang         | string | "J"     | Language (J = Japanese). |
| stats_field  | string | null    | Optional statsField code (e.g. 02=人口・世帯, 07=企業・家計・経済). |
| keyword      | string | null    | Optional search term (matched in statistics name, category, gov org). |
| limit        | int    | 20      | Max number of datasets to return. |

Returns a list of dicts with `statsDataId`, `statistics_name`, `main_category_name`, `sub_category_name`, `gov_org_name`, `statsField`, `surveyYears`.

### retrieve_and_process

| Parameter             | Type   | Default   | Description |
|-----------------------|--------|-----------|-------------|
| stats_data_id         | string | (required)| e.g. 0002111847 (from discover_datasets). |
| year                  | string | "2024"    | Survey year. |
| lang                  | string | "J"       | Language. |
| output_format         | string | "parquet" | "parquet" or "csv" (used only when save_to_disk is True). |
| save_to_disk          | bool   | false     | If true, write raw JSON and processed table to disk and return `path`. If false (default), return data in the response (no disk write). |
| max_rows_in_response  | int    | 2000      | When save_to_disk is false, include at most this many rows in the response; `row_count` is always the full count. |

**When save_to_disk is false (default):** Returns `ok`, `row_count`, `columns`, `rows_sample` (list of row dicts, capped by max_rows_in_response), `truncated` (true if more rows exist), `path` (null), and `error` (if any). Data is not written to disk; use this so Claude can answer questions from the returned rows.

**When save_to_disk is true:** Returns `ok`, `path` (to the processed file), `rows`, and `error` (if any).

Requires `ESTAT_APP_ID` in the environment or `.env`.
