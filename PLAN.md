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

### 2.2 Directory Layout (current)
```
kumonjo/
├── data/
│   ├── official/          # Reference data (statsfield.csv: 大分類/小分類 codes)
│   ├── raw/                # Gitignored; raw API JSON from retrievers
│   └── processed/          # Gitignored; cleaned CSVs/parquet from retrievers
├── kaiten/                 # Retrieval package + CLI scripts
│   ├── core/
│   │   ├── argparser.py
│   │   └── retrievers/
│   │       ├── core_retriever.py
│   │       ├── stats_data_ids_retriever.py
│   │       └── stats_data_id_table_retriever.py
│   └── scripts/
│       ├── run_stats_data_ids_retriever.py
│       └── run_stats_data_id_table_retriever.py
├── tansaku/                # Gitignored; exploratory notebooks
│   ├── data_processing_01_retrieve_table_list.ipynb
│   └── data_processing_02.ipynb
├── README.md
└── PLAN.md (this file)
```

### 2.3 What the Existing Logic Does (Reminder)

#### A. `data/official/statsfield.csv`
- **Purpose**: Official list of e-Stat **statsField** codes (大分類コード, 小分類コード, etc.).
- **Usage**: Scripts use **大分類コード** to decide which statsFields to call getStatsList for (e.g. "02" = 人口・世帯).

#### B. Retriever 1: **List of datasets (statsDataIds) by classification**
- **Files**: `stats_data_ids_retriever.py`, `run_stats_data_ids_retriever.py`
- **Flow**:
  1. Read `data/official/statsfield.csv` → get unique 大分類コード.
  2. For each statsField and a given **year**, call **getStatsList** (SingleStatsFieldTableFetcher).
  3. Parse `TABLE_INF` from response → one row per table (statsDataId, statistics_name, title, cycle, survey_date, gov_org, categories, etc.).
  4. **Clean**: lowercase column names, flatten JSON fields (STAT_NAME, GOV_ORG, MAIN_CATEGORY, SUB_CATEGORY, STATISTICS_NAME_SPEC, TITLE_SPEC) into code/name columns.
  5. Save: raw JSON under `data/raw/{lang}/statsField/`, processed CSV under `data/processed/{lang}/listOfStatsFields/{year}_list_of_statsDataIds.csv`.
- **Reminder**: This answers “what datasets exist for this category and year?” and produces the **catalog** used by the next retriever.

#### C. Retriever 2: **Actual table data for a given statsDataId**
- **Files**: `stats_data_id_table_retriever.py`, `run_stats_data_id_table_retriever.py`
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

The **kaiten** retrievers already implement most of this; the notebooks contain duplicate/exploratory versions. The plan is to treat **kaiten** as the source of truth and add any missing pieces (e.g. `extract_table_info`) into a shared module used by both CLI and MCP.

---

## 3. Gaps and Reorganization

### 3.1 Gaps
- **Dataset discovery for “user question”**: No tool that maps a **natural language question** (e.g. “2024年の雇用統計は？”) to recommended statsFields or statsDataIds. This needs either:
  - Semantic search over catalog (listOfStatsFields + metadata), or
  - Keyword/classification rules, or
  - Both.
- **MCP layer**: No MCP server or tools yet; current code is CLI/script-only.
- **Analysis**: No analysis module; scope TBD.
- **Orchestrator**: No chatbot/orchestrator; to be added with Claude Desktop integration.
- **Package structure**: Retrievers live under `kaiten` and use relative imports/path hacks; not a clean package for MCP to call.
- **Typo**: `kaiten/core/retrievers/__initi__.py` should be `__init__.py`.

### 3.2 Reorganization Goals
- **Single library** that both CLI scripts and MCP tools can import (no duplicate logic).
- **Clear pipeline**: discovery → retrieval/processing → analysis, so the orchestrator can call MCP tools in sequence.
- **Stable data paths**: configurable base dir for raw/processed so MCP and CLI share the same layout.

---

## 4. Proposed Direction (High Level)

### 4.1 Directory Structure (Phase 1 implemented)
```
kumonjo/
├── kumonjo/                       # Package (replaces former kaiten/)
│   ├── __init__.py
│   ├── config.py                  # Paths, load ESTAT_APP_ID from .env
│   ├── api/
│   │   ├── __init__.py
│   │   └── client.py              # getStatsList, getStatsData
│   ├── processing/
│   │   ├── __init__.py
│   │   ├── clean_list.py           # clean listOfStatsFields
│   │   └── parse_response.py     # extract_annotations_*, extract_values_raw, extract_data_from_response, extract_table_info, reorder_df_columns
│   └── retrieval/
│       ├── __init__.py
│       ├── list_tables.py          # fetch_list_of_tables
│       └── get_table.py            # fetch_table
├── scripts/                       # Thin CLIs (use ESTAT_APP_ID from .env)
│   ├── run_list_tables.py
│   └── run_get_tables.py
├── data/
│   ├── official/
│   ├── raw/
│   └── processed/
├── tansaku/                       # Keep as-is; reference only
├── .env.example                   # ESTAT_APP_ID=...
├── requirements.txt
├── README.md
└── PLAN.md
```

`kaiten/` has been removed; all retrieval/processing logic lives in `kumonjo/`. Discovery and MCP will be added in later phases.

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
- [ ] Introduce `src/kumonjo` (or keep `kaiten` but fix imports and package layout).
- [ ] Fix `__initi__.py` → `__init__.py` in retrievers.
- [ ] Extract shared logic: e-Stat client, list cleaning, response parsing (annotations + values + merge + table_info) into a single module set used by both current scripts and future MCP.
- [ ] Ensure scripts run against current data layout (data/raw, data/processed) and optionally use a config for paths.

### Phase 2: MCP server and “discovery” + “retrieval” tools
- [x] Add MCP server (Python, stdio via FastMCP) in **mcp_server/server.py** (folder named mcp_server to avoid shadowing the `mcp` package).
- [x] Tool **discover_datasets**: year, lang, stats_field, keyword, limit → list of statsDataIds + metadata from catalog (keyword/catalog-only). Catalog logic in **kumonjo/discovery/catalog.py**.
- [x] Tool **retrieve_and_process**: statsDataId, year, lang, output_format → path, rows, status. Wraps kumonjo retrieval + processing.
- [x] Document how to register this MCP server with Claude Desktop in **docs/MCP_CLAUDE_DESKTOP.md**.

### Phase 3: Analysis tool and scope
- [ ] Define analysis scope (e.g. summary stats, time series, filters).
- [ ] Implement **analyze** MCP tool that takes a table (or path) + analysis type and returns result.
- [ ] Optionally add **extract_table_info** to retrieval/processing and expose as a small “metadata” tool.

### Phase 4: Orchestrator and UX
- [ ] Configure Claude Desktop to use the MCP server; optional custom instructions for “use discover → retrieve → analyze” flow.
- [ ] Iterate on prompts and tool descriptions (in Japanese/English) so the model chooses the right tools and interprets government data correctly.

---

## 6. Data Conventions (reminder)

- **Lang**: `J` (Japanese) by default.
- **Paths**:
  - Raw: `data/raw/{lang}/statsField/`, `data/raw/{lang}/statsDataId/`.
  - Processed: `data/processed/{lang}/listOfStatsFields/`, `data/processed/{lang}/statsDataId/`.
- **Catalog CSV**: `{year}_list_of_statsDataIds.csv` with columns including statsDataId, statistics_name, title, statsField, surveyYears, gov_org_name, main_category_name, sub_category_name, etc.
- **Table output**: One file per statsDataId, e.g. `{year}_statsDataId_{id}.parquet`, with dimension labels merged (e.g. area_name, time_name, value).

---

## 7. Next Steps

1. Confirm or adjust the directory structure (e.g. keep `kaiten` vs. move to `src/kumonjo`).
2. Implement Phase 1 (modularize + fix typo).
3. Add a minimal MCP server and the two tools (discover_datasets, retrieve_and_process), then test with Claude Desktop.
4. Define and implement the analysis tool (Phase 3) in a later iteration.

This plan is intended to be iterated: once the first version of the plan is in place, we can refine phases and file layout as you go.
