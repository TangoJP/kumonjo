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
  Output: `data/raw/{lang}/statsField/` (raw JSON), `data/processed/{lang}/listOfStatsFields/{year}_list_of_statsDataIds.csv`.

- **Fetch table data** for statsDataIds in the catalog (filter by statsField):
  ```bash
  python scripts/run_get_tables.py --year 2024 --statsField 07
  ```
  To fetch a single table: `--statsDataId 0002111847`. Output: `data/raw/{lang}/statsDataId/`, `data/processed/{lang}/statsDataId/*.parquet`.

See [PLAN.md](PLAN.md) for the full roadmap (MCP, discovery, analysis).
