# kumonjo

Data project for government data of Japan (e-Stat API). Phase 1 provides a `kumonjo` package and CLI scripts to fetch catalog (list of statsDataIds) and table data.

## Setup

1. Create a virtualenv and install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` and set your e-Stat application ID:
   ```bash
   cp .env.example .env
   # Edit .env: ESTAT_APP_ID=your_app_id
   ```
   Get an app ID at [e-Stat](https://www.e-stat.go.jp/).

## Usage

Run from the project root so `kumonjo` is importable (or set `PYTHONPATH=.`).

- **Fetch list of tables (catalog)** for all statsFields and a year:
  ```bash
  python scripts/run_list_tables.py --year 2024
  ```
  Output: `data/raw/{lang}/statsField/` (raw JSON), `data/processed/{lang}/listOfStatsFields/{year}_list_of_statsDataIds.csv`. Optionally run `run_build_catalog.py` to build a single consolidated catalog for efficient MCP lookups.

- **Build consolidated catalog** (optional, for efficient MCP discovery):
  ```bash
  python scripts/run_build_catalog.py
  ```
  Parses all JSON under `data/raw/{lang}/statsField/` and writes `data/processed/{lang}/catalog_full.parquet`. MCP discovery uses this when present for faster lookups.

- **Fetch table data** for statsDataIds in the catalog (filter by statsField):
  ```bash
  python scripts/run_get_tables.py --year 2024 --statsField 07
  ```
  To fetch a single table: `--statsDataId 0002111847`. Output: `data/raw/{lang}/statsDataId/`, `data/processed/{lang}/statsDataId/*.parquet`.

## MCP server (Phase 2)

An MCP server exposes **discover_datasets** and **retrieve_and_process** for use with Claude Desktop (or other MCP clients).

- **Run server** (stdio, from project root): `python mcp_server/server.py`
- **Add to Claude Desktop**: see [docs/MCP_CLAUDE_DESKTOP.md](docs/MCP_CLAUDE_DESKTOP.md) for config and tool parameters.

See [PLAN.md](PLAN.md) for the full roadmap (discovery, analysis, orchestrator).
