"""Run basic analysis on a table (columns + rows from retrieve_and_process)."""

from typing import Any

import pandas as pd

# Time-like column names to try when inferring (order matters)
_TIME_COLUMN_CANDIDATES = ("time_name", "year", "survey_year", "time", "period", "年月")


def table_from_columns_rows(columns: list[str], rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Build a DataFrame from columns and rows (e.g. from retrieve_and_process)."""
    if not columns or not rows:
        return pd.DataFrame(columns=columns or None)
    return pd.DataFrame(rows, columns=columns)


def ensure_numeric_value_column(
    df: pd.DataFrame,
    value_column: str = "value",
) -> pd.DataFrame:
    """
    Coerce the value column to numeric. Non-numeric, '-', empty -> NaN.
    Returns df with value_column as float; does not modify if column missing.
    """
    if value_column not in df.columns:
        return df
    s = pd.to_numeric(df[value_column].astype(str).replace("", None).replace("-", None), errors="coerce")
    df = df.copy()
    df[value_column] = s
    return df


def infer_time_column(df: pd.DataFrame) -> str | None:
    """Return the first column name that looks like a time dimension, or None."""
    cols_lower = {c: c.lower() for c in df.columns}
    for candidate in _TIME_COLUMN_CANDIDATES:
        for col in df.columns:
            if candidate in cols_lower.get(col, ""):
                return col
    return None


def run_analysis(
    columns: list[str],
    rows: list[dict[str, Any]],
    analysis_type: str,
    *,
    value_column: str = "value",
    # filter
    filter_column: str | None = None,
    filter_value: Any = None,
    filter_values: list[Any] | None = None,
    # aggregate
    group_by: list[str] | None = None,
    agg: str = "sum",
    # time_series
    time_column: str | None = None,
    # top_bottom
    n: int = 10,
    order: str = "top",
) -> dict[str, Any]:
    """
    Run one basic analysis on a table. Table is given as columns + rows (from retrieve_and_process).

    analysis_type: "summary" | "filter" | "aggregate" | "time_series" | "top_bottom"
    value_column: name of numeric column (default "value"); coerced to numeric.
    filter_*: for filter — either filter_column + filter_value, or filter_column + filter_values (list).
    group_by, agg: for aggregate — group_by list of columns, agg one of "sum"|"mean"|"count".
    time_column: for time_series — optional; inferred from column names if not set.
    n, order: for top_bottom — n (int), order "top" or "bottom"; optional group_by.

    Returns dict with "type", "result" (fixed schema per type), and optional "meta", "warnings".
    """
    df = table_from_columns_rows(columns, rows)
    if df.empty:
        return {"type": analysis_type, "result": {}, "meta": {"row_count": 0}, "warnings": ["Table is empty"]}

    df = ensure_numeric_value_column(df, value_column=value_column)

    at = analysis_type.strip().lower()
    if at == "summary":
        return _run_summary(df, value_column=value_column)
    if at == "filter":
        return _run_filter(
            df,
            filter_column=filter_column,
            filter_value=filter_value,
            filter_values=filter_values,
        )
    if at == "aggregate":
        return _run_aggregate(df, value_column=value_column, group_by=group_by or [], agg=agg)
    if at == "time_series":
        return _run_time_series(df, value_column=value_column, time_column=time_column)
    if at == "top_bottom":
        return _run_top_bottom(
            df,
            value_column=value_column,
            n=n,
            order=order,
            group_by=group_by,
        )
    return {
        "type": analysis_type,
        "result": {},
        "meta": {},
        "warnings": [f"Unknown analysis_type: {analysis_type}. Use summary, filter, aggregate, time_series, top_bottom."],
    }


def _run_summary(df: pd.DataFrame, value_column: str = "value") -> dict[str, Any]:
    """Summary stats on the value column."""
    if value_column not in df.columns:
        return {
            "type": "summary",
            "result": {},
            "meta": {"value_column": value_column, "row_count": len(df)},
            "warnings": [f"Column '{value_column}' not found. Columns: {list(df.columns)}"],
        }
    s = df[value_column]
    valid = s.dropna()
    count_valid = int(valid.count())
    result = {
        "count": count_valid,
        "mean": float(valid.mean()) if count_valid else None,
        "median": float(valid.median()) if count_valid else None,
        "min": float(valid.min()) if count_valid else None,
        "max": float(valid.max()) if count_valid else None,
        "std": float(valid.std()) if count_valid and len(valid) > 1 else None,
        "sum": float(valid.sum()) if count_valid else None,
    }
    return {
        "type": "summary",
        "result": result,
        "meta": {"value_column": value_column, "row_count": len(df), "null_count": int(s.isna().sum())},
    }


def _run_filter(
    df: pd.DataFrame,
    filter_column: str | None = None,
    filter_value: Any = None,
    filter_values: list[Any] | None = None,
) -> dict[str, Any]:
    """Subset rows by column value(s)."""
    if not filter_column or filter_column not in df.columns:
        return {
            "type": "filter",
            "result": {"rows": [], "columns": list(df.columns), "row_count": 0},
            "meta": {},
            "warnings": [f"filter_column '{filter_column}' missing or not in table. Columns: {list(df.columns)}"],
        }
    if filter_values is not None:
        mask = df[filter_column].isin(filter_values)
    elif filter_value is not None:
        mask = df[filter_column] == filter_value
    else:
        return {
            "type": "filter",
            "result": {"rows": [], "columns": list(df.columns), "row_count": 0},
            "meta": {},
            "warnings": ["Provide either filter_value or filter_values."],
        }
    out = df.loc[mask]
    rows = out.to_dict("records")
    # Coerce non-JSON-serializable
    for r in rows:
        for k, v in list(r.items()):
            if isinstance(v, (pd.Timestamp,)):
                r[k] = str(v)
            elif isinstance(v, float) and v != v:
                r[k] = None
    return {
        "type": "filter",
        "result": {"columns": list(df.columns), "rows": rows, "row_count": len(rows)},
        "meta": {"filter_column": filter_column},
    }


def _run_aggregate(
    df: pd.DataFrame,
    value_column: str = "value",
    group_by: list[str] | None = None,
    agg: str = "sum",
) -> dict[str, Any]:
    """Group by columns and aggregate value column."""
    if value_column not in df.columns:
        return {
            "type": "aggregate",
            "result": {"groups": [], "row_count": 0},
            "meta": {"value_column": value_column, "group_by": group_by or []},
            "warnings": [f"Column '{value_column}' not found."],
        }
    gb = group_by or []
    missing = [c for c in gb if c not in df.columns]
    if missing:
        return {
            "type": "aggregate",
            "result": {"groups": [], "row_count": 0},
            "meta": {"value_column": value_column, "group_by": gb},
            "warnings": [f"group_by columns not in table: {missing}. Columns: {list(df.columns)}"],
        }
    agg = agg.strip().lower()
    if agg not in ("sum", "mean", "count"):
        agg = "sum"
    if not gb:
        # No group_by: single aggregate over whole table
        s = df[value_column].dropna()
        if agg == "count":
            val = int(s.count())
        else:
            val = float(getattr(s, agg)())
        return {
            "type": "aggregate",
            "result": {"groups": [{"value": val}], "row_count": 1},
            "meta": {"value_column": value_column, "group_by": [], "agg": agg},
        }
    out = df.groupby(gb, dropna=False)[value_column].agg(agg).reset_index()
    out.columns = list(out.columns[:-1]) + ["value"]
    rows = out.to_dict("records")
    for r in rows:
        for k, v in list(r.items()):
            if isinstance(v, (pd.Timestamp,)):
                r[k] = str(v)
            elif isinstance(v, float) and v != v:
                r[k] = None
    return {
        "type": "aggregate",
        "result": {"columns": list(out.columns), "groups": rows, "row_count": len(rows)},
        "meta": {"value_column": value_column, "group_by": gb, "agg": agg},
    }


def _run_time_series(
    df: pd.DataFrame,
    value_column: str = "value",
    time_column: str | None = None,
) -> dict[str, Any]:
    """Aggregate value by time dimension (sum per time period)."""
    if value_column not in df.columns:
        return {
            "type": "time_series",
            "result": {"points": [], "row_count": 0},
            "meta": {"value_column": value_column},
            "warnings": [f"Column '{value_column}' not found."],
        }
    tc = time_column or infer_time_column(df)
    if not tc or tc not in df.columns:
        return {
            "type": "time_series",
            "result": {"points": [], "row_count": 0},
            "meta": {"value_column": value_column, "time_column": None},
            "warnings": ["No time column found or specified. Try time_column (e.g. time_name, year)."],
        }
    out = df.groupby(tc, dropna=False)[value_column].sum().reset_index()
    out.columns = ["time", "value"]
    points = out.to_dict("records")
    for p in points:
        if isinstance(p.get("time"), (pd.Timestamp,)):
            p["time"] = str(p["time"])
    return {
        "type": "time_series",
        "result": {"time_column": tc, "points": points, "row_count": len(points)},
        "meta": {"value_column": value_column, "time_column": tc},
    }


def _run_top_bottom(
    df: pd.DataFrame,
    value_column: str = "value",
    n: int = 10,
    order: str = "top",
    group_by: list[str] | None = None,
) -> dict[str, Any]:
    """Top N or bottom N by value; optionally per group."""
    if value_column not in df.columns:
        return {
            "type": "top_bottom",
            "result": {"rows": [], "row_count": 0},
            "meta": {"value_column": value_column, "n": n, "order": order},
            "warnings": [f"Column '{value_column}' not found."],
        }
    n = max(1, min(n, 1000))
    order = order.strip().lower()
    ascending = order == "bottom"
    if group_by:
        missing = [c for c in group_by if c not in df.columns]
        if missing:
            return {
                "type": "top_bottom",
                "result": {"rows": [], "row_count": 0},
                "meta": {"value_column": value_column, "n": n, "order": order, "group_by": group_by},
                "warnings": [f"group_by columns not in table: {missing}."],
            }
        # Per-group: take top/bottom n within each group
        out = (
            df.sort_values(value_column, ascending=ascending)
            .groupby(group_by, dropna=False)
            .head(n)
            .reset_index(drop=True)
        )
    else:
        out = df.nsmallest(n, value_column) if ascending else df.nlargest(n, value_column)
    rows = out.to_dict("records")
    for r in rows:
        for k, v in list(r.items()):
            if isinstance(v, (pd.Timestamp,)):
                r[k] = str(v)
            elif isinstance(v, float) and v != v:
                r[k] = None
    return {
        "type": "top_bottom",
        "result": {"columns": list(out.columns), "rows": rows, "row_count": len(rows)},
        "meta": {"value_column": value_column, "n": n, "order": order, "group_by": group_by or []},
    }
