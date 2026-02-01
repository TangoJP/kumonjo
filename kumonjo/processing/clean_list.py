"""Clean getStatsList TABLE_INF into a catalog DataFrame."""

from datetime import date

import pandas as pd


def clean_list_of_tables(
    df: pd.DataFrame,
    run_date: str | None = None,
) -> pd.DataFrame:
    """
    Rename and flatten columns from getStatsList TABLE_INF so the result
    is a clean catalog (statsDataId, statistics_name, title, statsField, etc.).
    """
    if df.empty:
        return df

    cols_to_lower = [
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
    renamer = {k: k.lower() for k in cols_to_lower}
    renamer["@id"] = "statsDataId"
    df = df.rename(columns=renamer)

    cols_json = ["STAT_NAME", "GOV_ORG", "MAIN_CATEGORY", "SUB_CATEGORY"]
    for c in cols_json:
        if c in df.columns:
            df[c.lower() + "_code"] = df[c].apply(lambda x: x.get("@code") if isinstance(x, dict) else None)
            df[c.lower() + "_name"] = df[c].apply(lambda x: x.get("$") if isinstance(x, dict) else None)

    if "STATISTICS_NAME_SPEC" in df.columns:
        df["statistics_name_spec_category"] = df["STATISTICS_NAME_SPEC"].apply(
            lambda x: x.get("TABULATION_CATEGORY") if isinstance(x, dict) else None
        )
        df["statistics_name_spec_sub_category1"] = df["STATISTICS_NAME_SPEC"].apply(
            lambda x: x.get("TABULATION_SUB_CATEGORY1") if isinstance(x, dict) else None
        )
    if "TITLE_SPEC" in df.columns:
        df["title_spec_name"] = df["TITLE_SPEC"].apply(
            lambda x: x.get("TABLE_NAME") if isinstance(x, dict) else None
        )
        df["title_spec_explanation"] = df["TITLE_SPEC"].apply(
            lambda x: x.get("TABLE_EXPLANATION") if isinstance(x, dict) else None
        )

    drop_cols = [c for c in cols_json + ["STATISTICS_NAME_SPEC", "TITLE_SPEC"] if c in df.columns]
    df = df.drop(columns=drop_cols, errors="ignore")

    if run_date is None:
        run_date = date.today().strftime("%Y%m%d")
    df["retrieval_date"] = run_date

    return df
