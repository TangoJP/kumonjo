"""Parse getStatsData response: CLASS_OBJ annotations + VALUE -> merged DataFrame."""

from typing import Any

import pandas as pd


def extract_annotations_single(class_obj: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten one CLASS_OBJ (dict or list of CLASS items) into annotation rows."""
    annotations_top = {k: v for k, v in class_obj.items() if k != "CLASS"}
    classes = class_obj.get("CLASS")

    if isinstance(classes, dict):
        for k, v in classes.items():
            annotations_top[k] = v
        annotations_top["@level"] = "0"
        return [annotations_top]

    if isinstance(classes, list):
        out = []
        for cls in classes:
            row = annotations_top.copy()
            for k, v in cls.items():
                row[k] = v
            out.append(row)
        return out

    raise TypeError("CLASS is not dict nor list")


def extract_annotations_whole(
    response: dict[str, Any],
    clean_column_names: bool = True,
) -> pd.DataFrame:
    """Build annotations DataFrame from GET_STATS_DATA.STATISTICAL_DATA.CLASS_INF.CLASS_OBJ."""
    class_objs = (
        response.get("GET_STATS_DATA", {})
        .get("STATISTICAL_DATA", {})
        .get("CLASS_INF", {})
        .get("CLASS_OBJ", [])
    )
    if not isinstance(class_objs, list):
        raise TypeError("CLASS_OBJ is not a list")

    rows = []
    for obj in class_objs:
        rows.extend(extract_annotations_single(obj))

    df = pd.DataFrame(rows)
    if clean_column_names and not df.empty:
        df = df.rename(columns={c: c.replace("@", "") for c in df.columns})
    return df


def extract_values_raw(response: dict[str, Any]) -> pd.DataFrame:
    """Build DataFrame from GET_STATS_DATA.STATISTICAL_DATA.DATA_INF.VALUE."""
    values = (
        response.get("GET_STATS_DATA", {})
        .get("STATISTICAL_DATA", {})
        .get("DATA_INF", {})
        .get("VALUE", [])
    )
    df = pd.DataFrame(values)
    if df.empty:
        return df
    renamer = {c: c.replace("@", "") for c in df.columns}
    renamer["$"] = "value"
    return df.rename(columns=renamer)


def extract_data_from_response(response: dict[str, Any]) -> pd.DataFrame:
    """
    Merge annotations into VALUE so each dimension has human-readable columns
    (e.g. area_name, time_name) plus value.
    """
    df_annot = extract_annotations_whole(response, clean_column_names=True)
    df_values = extract_values_raw(response)

    if df_annot.empty or df_values.empty:
        return pd.DataFrame()

    for col_id in df_annot["id"].unique():
        sub = df_annot[df_annot["id"] == col_id]
        if "unit" in sub.columns:
            sub = sub.drop(columns=["unit"], errors="ignore")
        cols_sub = [c for c in sub.columns if c != "id"]
        if col_id not in df_values.columns:
            continue
        df_values = df_values.merge(
            sub,
            how="left",
            left_on=col_id,
            right_on="code",
        )
        df_values = df_values.rename(columns={k: f"{col_id}_{k}" for k in cols_sub})
        df_values = df_values.drop(columns=[col_id, "id"], errors="ignore")

    return df_values


def reorder_df_columns(df: pd.DataFrame, offset: int = 2) -> pd.DataFrame:
    """Move first `offset` columns (e.g. unit, value) to the end."""
    if df.empty or offset <= 0 or offset >= len(df.columns):
        return df
    cols = list(df.columns)
    return df[cols[offset:] + cols[:offset]]


def _clean_key(key: str) -> str:
    return key.replace("_$", "").replace("@", "").replace("_no", "")


def extract_table_info(response: dict[str, Any]) -> pd.DataFrame:
    """Extract TABLE_INF metadata as a two-column DataFrame (column, information)."""
    table_inf = (
        response.get("GET_STATS_DATA", {})
        .get("STATISTICAL_DATA", {})
        .get("TABLE_INF", {})
    )
    if not isinstance(table_inf, dict):
        raise TypeError("TABLE_INF is not a dict")

    out = {}
    for k, v in table_inf.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                out[_clean_key(f"{k}_{k2}")] = v2
        else:
            out[_clean_key(k)] = v

    return pd.DataFrame(list(out.items()), columns=["column", "information"])
