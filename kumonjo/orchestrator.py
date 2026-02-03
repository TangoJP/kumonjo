"""
Orchestrator: accept user question → discover datasets → retrieve table data.

Implements Phase 5-1 from PLAN.md (§4.4):
1. Accept input: user question (natural language) + optional year, lang, limit
2. Map to discovery params: extract keyword from question
3. Discover: call search_catalog → list of statsDataIds + metadata
4. Choose targets: take top N statsDataId(s)
5. Retrieve: call fetch_table for each → table data (columns, rows)
6. Return: structured result (discovered list + retrieved tables)

Analysis step (Phase 4) will be added later.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
import pandas as pd

from kumonjo.config import get_api_key
from kumonjo.discovery.catalog import search_catalog
from kumonjo.retrieval.get_table import fetch_table

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorResult:
    """Result from orchestrator run."""

    question: str
    year: str
    lang: str
    discovered: list[dict] = field(default_factory=list)
    retrieved: list[dict] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "question": self.question,
            "year": self.year,
            "lang": self.lang,
            "discovered_count": len(self.discovered),
            "discovered": self.discovered,
            "retrieved_count": len(self.retrieved),
            "retrieved": self.retrieved,
            "error": self.error,
        }


def extract_params_from_question(question: str) -> dict[str, str | None]:
    """
    Extract discovery parameters from a natural language question.

    Currently extracts:
    - year: 4-digit year mentioned in the question (e.g., "2024年" → "2024")
    - keyword: the question itself (for now; could be refined to extract key terms)

    Future: could use NLP or rules to extract stats_field, specific terms, etc.
    """
    params: dict[str, str | None] = {
        "year": None,
        "keyword": None,
        "stats_field": None,
    }

    # Extract year: look for 4-digit year pattern (e.g., 2024, 2024年)
    year_match = re.search(r"(20\d{2}|19\d{2})", question)
    if year_match:
        params["year"] = year_match.group(1)

    # For now, use the entire question as keyword (search_catalog will match against
    # statistics_name, category names, etc.)
    # Remove year from keyword to avoid redundant matching
    keyword = question
    if year_match:
        keyword = re.sub(r"(20\d{2}|19\d{2})年?の?", "", keyword).strip()
    params["keyword"] = keyword if keyword else None

    return params


def _df_to_rows(df: pd.DataFrame, max_rows: int = 2000) -> tuple[list[str], list[dict], int, bool]:
    """Convert DataFrame to columns and rows for JSON serialization."""
    columns = list(df.columns)
    total_rows = len(df)
    truncated = total_rows > max_rows

    sample = df.head(max_rows) if truncated else df
    rows = []
    for _, row in sample.iterrows():
        row_dict = {}
        for col in columns:
            val = row[col]
            if val is None or (isinstance(val, float) and val != val):  # NaN check
                row_dict[col] = None
            elif isinstance(val, (str, int, float)):
                row_dict[col] = val
            else:
                row_dict[col] = str(val)
        rows.append(row_dict)

    return columns, rows, total_rows, truncated


def run_orchestrator(
    question: str,
    year: str | None = None,
    lang: str = "J",
    discover_limit: int = 5,
    retrieve_limit: int = 1,
    max_rows_per_table: int = 2000,
) -> OrchestratorResult:
    """
    Main orchestrator function: question → discover → retrieve → result.

    Args:
        question: User's natural language question (e.g., "2024年の雇用統計は？")
        year: Override year for discovery (if not extracted from question)
        lang: Language code (default "J" for Japanese)
        discover_limit: Max datasets to return from discovery
        retrieve_limit: Max datasets to actually retrieve (top N from discovered)
        max_rows_per_table: Max rows to include per retrieved table

    Returns:
        OrchestratorResult with discovered datasets and retrieved table data
    """
    result = OrchestratorResult(question=question, year=year or "", lang=lang)

    # Step 1: Extract params from question
    extracted = extract_params_from_question(question)
    effective_year = year or extracted.get("year") or "2024"
    keyword = extracted.get("keyword")
    stats_field = extracted.get("stats_field")

    result.year = effective_year
    logger.info(
        "Orchestrator: question=%r year=%s keyword=%r stats_field=%r",
        question,
        effective_year,
        keyword,
        stats_field,
    )

    # Step 2: Discover datasets
    try:
        discovered = search_catalog(
            year=effective_year,
            lang=lang,
            stats_field=stats_field,
            keyword=keyword,
            limit=discover_limit,
        )
    except Exception as e:
        logger.error("Discovery failed: %s", e)
        result.error = f"Discovery failed: {e}"
        return result

    # Handle timeout or error from search_catalog
    if discovered and isinstance(discovered[0], dict) and discovered[0].get("error"):
        result.error = discovered[0].get("message", "Discovery error")
        return result

    result.discovered = discovered
    logger.info("Discovered %d datasets", len(discovered))

    if not discovered:
        result.error = "No datasets found matching the query."
        return result

    # Step 3: Retrieve top N datasets
    try:
        app_id = get_api_key()
    except ValueError as e:
        result.error = str(e)
        return result

    targets = discovered[:retrieve_limit]
    for dataset in targets:
        stats_data_id = dataset.get("statsDataId")
        if not stats_data_id:
            continue

        logger.info("Retrieving statsDataId=%s", stats_data_id)
        try:
            df = fetch_table(
                app_id=app_id,
                stats_data_id=stats_data_id,
                year=effective_year,
                lang=lang,
                save_to_disk=False,
            )
        except Exception as e:
            logger.error("Retrieval failed for %s: %s", stats_data_id, e)
            result.retrieved.append({
                "stats_data_id": stats_data_id,
                "metadata": dataset,
                "error": str(e),
                "columns": [],
                "rows": [],
                "row_count": 0,
                "truncated": False,
            })
            continue

        if df.empty:
            result.retrieved.append({
                "stats_data_id": stats_data_id,
                "metadata": dataset,
                "error": "No data extracted",
                "columns": [],
                "rows": [],
                "row_count": 0,
                "truncated": False,
            })
            continue

        columns, rows, row_count, truncated = _df_to_rows(df, max_rows_per_table)
        result.retrieved.append({
            "stats_data_id": stats_data_id,
            "metadata": dataset,
            "error": None,
            "columns": columns,
            "rows": rows,
            "row_count": row_count,
            "truncated": truncated,
        })
        logger.info(
            "Retrieved statsDataId=%s: %d rows (%d columns)",
            stats_data_id,
            row_count,
            len(columns),
        )

    return result
