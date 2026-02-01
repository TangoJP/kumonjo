# Kumonjo Project Plan: Government Data Chatbot with MCP

## 1. Project Scope

### 1.1 Overall Goal
Build a **chatbot** that uses **MCP (Model Context Protocol) tools** so users can ask questions about **government-provided data** (mainly Japan’s e-Stat). User input will mostly be in **Japanese**; code and variable names can stay in English.

### 1.2 Target MCP Tool Set (at least)
| # | Capability | Description |
|---|------------|-------------|
| 1 | **Dataset discovery** | Find datasets (statsDataIds, tables) that are relevant to the user’s question (e.g. by topic, year, category). |
| 2 | **Data retrieval & processing** | Fetch e-Stat data and turn raw API responses into usable tabular data (e.g. DataFrames / parquet). |
| 3 | **Data analysis** | Run analyses on retrieved data (scope TBD; e.g. aggregations, time series, simple stats). |
| 4 | **Chatbot orchestrator** | Accept user input and decide which MCP tools to call and in what order (initially via **Claude Desktop**). |

---

## 2. Current Codebase Overview

### 2.1 Data Source: e-Stat API (Japan)
- **e-Stat**: Government statistics portal; REST API at `https://api.e-stat.go.jp/rest/3.0/app/`.
- Main endpoints used:
  - **getStatsList**: List tables by `statsField` (classification) and `surveyYears` → returns table metadata and `statsDataId`s.
  - **getStatsData**: Get actual statistical data for a given `statsDataId` and `surveyYears` → returns JSON with dimensions (CLASS_OBJ) and values (VALUE).

### 2.2 Directory Layout (historical → see §4.1 for current)
The codebase was reorganized: **kaiten/** was replaced by **kumonjo/** (package), **scripts/** (CLIs), and **mcp_server/** (MCP). Notebooks remain under **tansaku/** for reference only.

### 2.3 What the Existing Logic Does (Reminder)

#### A. `data/official/statsfield.csv`
- **Purpose**: Official list of e-Stat **statsField** codes (大分類コード, 小分類コード, etc.).
- **Usage**: Scripts use **大分類コード** to decide which statsFields to call getStatsList for (e.g. "02" = 人口・世帯).

#### B. Retriever 1: **List of datasets (statsDataIds) by classification**
- **Files** (now): `kumonjo/retrieval/list_tables.py`, `scripts/run_list_tables.py` (formerly stats_data_ids_retriever, run_stats_data_ids_retriever).
- **Flow**:
  1. Read `data/official/statsfield.csv` → get unique 大分類コード.
  2. For each statsField and a given **year**, call **getStatsList** (SingleStatsFieldTableFetcher).
  3. Parse `TABLE_INF` from response → one row per table (statsDataId, statistics_name, title, cycle, survey_date, gov_org, categories, etc.).
  4. **Clean**: lowercase column names, flatten JSON fields (STAT_NAME, GOV_ORG, MAIN_CATEGORY, SUB_CATEGORY, STATISTICS_NAME_SPEC, TITLE_SPEC) into code/name columns.
  5. Save: raw JSON under `data/raw/{lang}/statsField/`, processed CSV under `data/processed/{lang}/listOfStatsFields/{year}_list_of_statsDataIds.csv`.
- **Reminder**: This answers “what datasets exist for this category and year?” and produces the **catalog** used by the next retriever.

#### C. Retriever 2: **Actual table data for a given statsDataId**
- **Files** (now): `kumonjo/retrieval/get_table.py`, `scripts/run_get_tables.py` (formerly stats_data_id_table_retriever).
- **Flow**:
  1. Read `data/processed/{lang}/listOfStatsFields/{year}_list_of_statsDataIds.csv`; optionally filter by `statsField`.
  2. For each statsDataId, call **getStatsData** (StatsDataIdTableRetriever).
  3. **Parse response**:
     - **CLASS_OBJ**: dimensions (e.g. area, time, cat01). Each class can be a single dict or a list of dicts; flatten to rows with id, name, code, level, unit.
     - **VALUE**: rows of dimension codes + `$` (value). Rename `$` → `value`, strip `@` from keys.
  4. **Merge**: Join VALUE with each dimension’s annotations (code → name, etc.) so the final table has human-readable columns (e.g. area_name, time_name) plus `value`.
  5. Reorder columns (value/unit first or similar), then save: raw JSON to `data/raw/{lang}/statsDataId/`, processed table to `data/processed/{lang}/statsDataId/` as **parquet** (or CSV).
- **Reminder**: This is the “actual data retrieval + processing” step; output is ready for analysis or for an MCP tool to return.

#### D. Base and shared behavior
- **core_retriever.py**: Abstract `BaseRetriever` with `api_key`, `base_url`, `session`, `set_base_url()`, `fetch()`, `save()`, `run()`. Parses CLI `--api_key`, `--year`.
- **argparser.py**: `EStatsArgParser` adds `--lang`, `--statsField`, `--statsDataId` for the table retriever script.

#### E. Notebooks (`tansaku/`) — logic to be modularized (do not edit notebooks)
- **data_processing_01_retrieve_table_list.ipynb**:
  - `get_tables_single_year_statsDataId(params)`: one getStatsList call.
  - `get_tables_multi_year_statsDataId(appId, stats_data_ids, years, lang)`: loop statsField × year, build DataFrame of TABLE_INF.
  - `clean_statsDataId_table(df_tables)`: same cleaning as `stats_data_ids_retriever` (rename, flatten STAT_NAME/GOV_ORG/MAIN/SUB, STATISTICS_NAME_SPEC, TITLE_SPEC).
- **data_processing_02.ipynb**:
  - `get_statsdata(params)`: one getStatsData call.
  - `get_statsdata_csv(params)`: Simple CSV endpoint (optional alternative).
  - `extract_annotations(class_objs)` / `extract_annotations_single` / `extract_annotations_whole`: CLASS_OBJ → annotation DataFrame (id, name, code, level, unit).
  - `extract_values_raw(response)`: VALUE → DataFrame with `value` and dimension columns.
  - `extract_data(response)`: merge annotations into values (same idea as StatsDataIdTableRetriever.extract_response).
  - `extract_table_info(response)`: TABLE_INF → table metadata DataFrame; `clean_key()` for key normalization.

The **kumonjo** package now holds the canonical retrieval/processing logic; the notebooks are reference only.

---

## 3. Gaps and Reorganization

### 3.1 Gaps (updated)
- **Dataset discovery for “user question”**: Keyword/catalog search is in place (discover_datasets, catalog_overview). Semantic or NL mapping (e.g. “2024年の雇用統計は？” → statsDataIds) could be added via embeddings or rules.
- **MCP layer**: Done — MCP server and discovery/retrieval tools exist (**mcp_server/server.py**).
- **Analysis**: No analysis module yet; scope TBD (Phase 3).
- **Orchestrator**: To be refined — Claude Desktop uses the MCP server; custom instructions and tool descriptions can be iterated (Phase 4).
- **Package structure**: Done — single library under **kumonjo/** used by both CLI and MCP.

### 3.2 Reorganization Goals
- **Single library** that both CLI scripts and MCP tools can import (no duplicate logic).
- **Clear pipeline**: discovery → retrieval/processing → analysis, so the orchestrator can call MCP tools in sequence.
- **Stable data paths**: configurable base dir for raw/processed so MCP and CLI share the same layout.

---

## 4. Proposed Direction (High Level)

### 4.1 Directory Structure (current)
```
kumonjo/
├── kumonjo/                       # Package
│   ├── __init__.py
│   ├── config.py                  # Paths, ESTAT_APP_ID from .env
│   ├── api/client.py              # getStatsList, getStatsData
│   ├── processing/
│   │   ├── clean_list.py           # clean listOfStatsFields (notebook parity)
│   │   └── parse_response.py      # extract_annotations_*, extract_values_raw, extract_data_from_response, reorder_df_columns
│   ├── retrieval/
│   │   ├── list_tables.py          # fetch_list_of_tables (+ pagination)
│   │   ├── get_table.py            # fetch_table
│   │   └── build_catalog.py        # consolidate raw/statsField → catalog_full.parquet
│   └── discovery/
│       └── catalog.py             # list_available_years, catalog_overview, load_catalog, search_catalog, list_stats_areas, list_stats_fields_for_year
├── mcp_server/
│   └── server.py                  # MCP tools: catalog_overview, list_stats_areas, list_stats_fields_for_year, list_available_years, discover_datasets, retrieve_and_process
├── scripts/
│   ├── run_list_tables.py
│   ├── run_get_tables.py
│   └── run_build_catalog.py
├── data/ official | raw | processed (catalog_full.parquet, listOfStatsFields/, statsDataId/)
├── tansaku/                       # Reference only; do not edit
├── docs/MCP_CLAUDE_DESKTOP.md
├── .env.example
├── requirements.txt
├── README.md
└── PLAN.md
```

### 4.2 Module Responsibilities (aligned with MCP)
- **api/client.py**: Single place for e-Stat GET calls (getStatsList, getStatsData); returns raw JSON/dict.
- **retrieval/list_tables.py**: Uses client + processing/clean_list → catalog DataFrame; can write to data/processed.
- **retrieval/get_table.py**: Uses client + processing/parse_response → one DataFrame per statsDataId; can write raw + processed.
- **discovery/catalog.py**: Load listOfStatsFields from disk; filter by year, statsField, keyword (e.g. in statistics_name, title).
- **discovery/search.py**: (Later) Map Japanese user question to statsField or statsDataIds (embeddings or rules).
- **MCP tools**: Call these modules and return results in the format the MCP protocol expects (e.g. JSON or file refs).

### 4.3 Pipeline for the Orchestrator
**The user interacts only with the chatbot from the start.** The chatbot decides when to call discovery, retrieval, and analysis (no separate “discovery UI” for the user).

1. User asks a question in natural language (e.g. in Japanese: 「2024年の雇用統計は？」).
2. **Discover**: Orchestrator calls MCP tool “discover_datasets” with the question (and optional year/category); tool returns a short list of relevant statsDataIds + metadata.
3. **Optional clarification**: Chatbot may show the user a few dataset options and ask which to use, or proceed with the top match(es).
4. **Retrieve**: Orchestrator calls “retrieve_and_process” for the chosen statsDataId(s); returns table(s) or paths.
5. **Analyze**: If needed, “analyze” runs on the retrieved table(s) (scope TBD).
6. Orchestrator summarizes and answers the user using tool outputs.

So discovery is an internal step the chatbot uses to *identify* which data to retrieve; the user does not run discovery separately.

---

## 5. Phased Plan

### Phase 1: Modularize and fix
- [x] **1-1** Replace `kaiten` with **kumonjo** package at repo root; fix imports and layout.
- [x] **1-2** Extract shared logic: e-Stat client (**api/client.py**), list cleaning (**processing/clean_list.py**), response parsing (**processing/parse_response.py**) used by CLI and MCP.
- [x] **1-3** Scripts use **config** for paths and ESTAT_APP_ID (.env); data layout data/raw, data/processed.

### Phase 2: Discovery (search, list, catalog — which datasets exist)
- [x] **2-1** MCP server (Python, stdio via FastMCP) in **mcp_server/server.py**.
- [x] **2-2** **catalog_overview**: years, dataset counts, optional stats_fields for a year, optional stats_areas (single lookup).
- [x] **2-3** **list_available_years**, **list_stats_areas**, **list_stats_fields_for_year**: optional alternatives to catalog_overview.
- [x] **2-4** **discover_datasets**: year, lang, stats_field, keyword, limit → list of statsDataIds + metadata from catalog (uses catalog_full.parquet when present).
- [x] **2-5** Consolidated catalog: **build_catalog** from raw/J/statsField → **catalog_full.parquet**; discovery uses it for fast lookups.
- [x] **2-6** Document MCP + Claude Desktop in **docs/MCP_CLAUDE_DESKTOP.md**.
- [ ] **2-7** **Search by stats_field with subcategories**: Within 大分類, return dataset counts by 小分類 (e.g. 人口・世帯 → 人口, 人口移動, 世帯).
- [ ] **2-8** **List datasets by government organization**: Filter/aggregate by 府省 (e.g. 総務省, 厚生労働省); dataset counts per gov_org.
- [ ] **2-9** **Time-series data discovery**: Find statistics available across multiple years (e.g. same statistics_name 2020–2024).
- [ ] **2-10** (TBD) **Similar-dataset search**: Suggest related datasets by statistics name or keyword (e.g. embeddings or e-Stat metadata).
- [ ] **2-11** (TBD) **Search history & favorites**: Persist search conditions or dataset IDs for re-use.

### Phase 3: Dataset retrieval (fetch, preview, metadata — actual data for discovered statsDataIds)
- [x] **3-1** **retrieve_and_process**: statsDataId, year, lang, output_format → path, rows, status.
- [ ] **3-2** (TBD) **Dataset preview**: Before retrieve: column names, row count, sample rows.
- [ ] **3-3** **Detailed dataset metadata**: Survey frequency (月次/年次), last updated, data period from e-Stat API.
- [ ] **3-4** (TBD) **Bulk retrieval**: Multiple statsDataIds in one call for batch/time-series download.
- [ ] **3-5** (TBD) **Dataset comparison**: Compare multiple datasets (name, size, column count) side-by-side.

### Phase 4: Analysis tool and scope
- [ ] **4-1** Define analysis scope (e.g. summary stats, time series, filters).
- [ ] **4-2** Implement **analyze** MCP tool that takes a table (or path) + analysis type and returns result.
- [ ] **4-3** Optionally add **extract_table_info** to retrieval/processing and expose as a small “metadata” tool.

### Phase 5: Orchestrator and UX
- [ ] **5-1** Configure Claude Desktop to use the MCP server; optional custom instructions for “use discover → retrieve → analyze” flow.
- [ ] **5-2** Iterate on prompts and tool descriptions (in Japanese/English) so the model chooses the right tools and interprets government data correctly.

---

## 6. Data Conventions

- **Lang**: `J` (Japanese) by default.
- **Paths**:
  - Raw: `data/raw/{lang}/statsField/`, `data/raw/{lang}/statsDataId/`.
  - Processed: `data/processed/{lang}/listOfStatsFields/`, `data/processed/{lang}/statsDataId/`, `data/processed/{lang}/catalog_full.parquet`.
- **Catalog**: Per-year CSV `{year}_list_of_statsDataIds.csv`; consolidated **catalog_full.parquet** (from run_build_catalog) used by MCP discovery when present. Columns include statsDataId, statistics_name, title, statsField, surveyYears, gov_org_name, main_category_name, sub_category_name, etc.
- **Table output**: One file per statsDataId, e.g. `{year}_statsDataId_{id}.parquet`, with dimension labels merged (e.g. area_name, time_name, value).

---

## 7. Next Steps

1. Phase 1 and Phase 2 (discovery core) are done. Refine tool descriptions and Claude Desktop instructions as needed.
2. Phase 3 (dataset retrieval): 3-1 done; implement 3-2–3-5 (preview, metadata, bulk, comparison) as needed.
3. Phase 2: implement remaining discovery items 2-7–2-11 (subcategories, gov_org, time-series, similar-dataset, history) as needed.
4. Phase 4 (analysis): define scope and implement analyze tool when ready.
5. Phase 5: iterate on orchestrator prompts and UX.

This plan is intended to be iterated as the project evolves.
