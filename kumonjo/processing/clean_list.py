"""
Clean getStatsList TABLE_INF into a catalog DataFrame.

Matches tansaku/data_processing_01_retrieve_table_list.ipynb clean_statsDataId_table()
with safe handling for None/non-dict values and title flattening for parquet.
"""

from datetime import date

import pandas as pd


def _safe_get(obj, key: str):
    """Return obj.get(key) if obj is dict, else None."""
    return obj.get(key) if isinstance(obj, dict) else None


def clean_list_of_tables(
    df: pd.DataFrame,
    run_date: str | None = None,
) -> pd.DataFrame:
    """
    Clean TABLE_INF from getStatsList (same logic as notebook clean_statsDataId_table).
    Renames columns, flattens JSON columns (STAT_NAME, GOV_ORG, MAIN_CATEGORY, SUB_CATEGORY,
    STATISTICS_NAME_SPEC, TITLE_SPEC), drops original JSON columns.
    Normalizes title to string (API may return dict e.g. {"$": "..."}) for parquet safety.
    """
    if df.empty:
        return df

    # Same renames as notebook clean_statsDataId_table
    cols_to_lower_case = [
        "STATISTICS_NAME",
        "TITLE",
        "CYCLE",
        "SURVEY_DATE",
        "OPEN_DATE",
        "SMALL_AREA",
        "COLLECT_AREA",
        "OVERALL_TOTAL_NUMBER",
        "UPDATED_DATE",
        "DESCRIPTION",
    ]
    renamer = {k: k.lower() for k in cols_to_lower_case}
    renamer["@id"] = "statsDataId"
    df = df.rename(columns=renamer)

    # Flatten title to string (API may return dict e.g. {"$": "..."} or {"@no": "001", "$": "..."})
    if "title" in df.columns:
        df["title"] = df["title"].apply(
            lambda x: _safe_get(x, "$") if isinstance(x, dict) else (x if isinstance(x, str) else None)
        )

    # Same JSON columns as notebook: STAT_NAME, GOV_ORG, MAIN_CATEGORY, SUB_CATEGORY
    cols_json = ["STAT_NAME", "GOV_ORG", "MAIN_CATEGORY", "SUB_CATEGORY"]
    for c in cols_json:
        if c in df.columns:
            df[c.lower() + "_code"] = df[c].apply(lambda x: _safe_get(x, "@code"))
            df[c.lower() + "_name"] = df[c].apply(lambda x: _safe_get(x, "$"))

    # Same as notebook: STATISTICS_NAME_SPEC -> category, sub_category1
    if "STATISTICS_NAME_SPEC" in df.columns:
        df["statistics_name_spec_category"] = df["STATISTICS_NAME_SPEC"].apply(
            lambda x: _safe_get(x, "TABULATION_CATEGORY")
        )
        df["statistics_name_spec_sub_category1"] = df["STATISTICS_NAME_SPEC"].apply(
            lambda x: _safe_get(x, "TABULATION_SUB_CATEGORY1")
        )

    # Same as notebook: TITLE_SPEC -> TABLE_NAME, TABLE_EXPLANATION
    if "TITLE_SPEC" in df.columns:
        df["title_spec_name"] = df["TITLE_SPEC"].apply(lambda x: _safe_get(x, "TABLE_NAME"))
        df["title_spec_explanation"] = df["TITLE_SPEC"].apply(lambda x: _safe_get(x, "TABLE_EXPLANATION"))

    # Same drop as notebook
    drop_cols = [c for c in cols_json + ["STATISTICS_NAME_SPEC", "TITLE_SPEC"] if c in df.columns]
    df = df.drop(columns=drop_cols, errors="ignore")

    if run_date is None:
        run_date = date.today().strftime("%Y%m%d")
    df["retrieval_date"] = run_date

    return df


# Alias for notebook parity
clean_statsDataId_table = clean_list_of_tables
