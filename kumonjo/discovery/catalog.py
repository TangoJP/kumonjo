"""Load and search the listOfStatsFields catalog (dataset discovery)."""

import functools
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path

import pandas as pd

from kumonjo.config import get_data_dirs

# Default timeout for catalog I/O and aggregation (seconds). Prevents hanging when used via MCP.
DEFAULT_CATALOG_TIMEOUT_SECONDS = 10.0


def _run_with_timeout(seconds: float, thunk, timeout_error_result):
    """Run thunk() in a thread; return its result or timeout_error_result if timeout."""
    with ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(thunk)
        try:
            return future.result(timeout=seconds)
        except FuturesTimeoutError:
            return timeout_error_result


# ---------------------------------------------------------------------------
# Cached helpers for statsfield.csv (avoids repeated file I/O)
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def _load_statsfield_df() -> pd.DataFrame:
    """Load statsfield.csv once and cache it."""
    dirs = get_data_dirs()
    path = dirs["official"] / "statsfield.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype="object", header=0)


@functools.lru_cache(maxsize=1)
def _get_stats_field_code_to_name() -> dict[str, str]:
    """Return cached mapping of statsField code -> name (大分類コード -> 大分類)."""
    df = _load_statsfield_df()
    if df.empty or "大分類コード" not in df.columns:
        return {}
    return {
        str(code).strip(): group["大分類"].iloc[0] if "大分類" in group.columns else ""
        for code, group in df.groupby("大分類コード", sort=False)
    }


def list_stats_areas(official_dir: Path | str | None = None) -> dict:
    """
    List all stats areas (大分類・小分類) from the official statsfield.csv.
    Use when the user asks "list of all stats areas" or "どの統計分野がある？".
    Returns dict with stats_areas (list of {code, name, sub_categories}), and message.
    """
    # Use cached df when official_dir is default
    if official_dir is None:
        df = _load_statsfield_df()
    else:
        path = Path(official_dir) / "statsfield.csv"
        if not path.exists():
            return {
                "stats_areas": [],
                "message": "公式の統計分野一覧（statsfield.csv）が見つかりません。",
            }
        df = pd.read_csv(path, dtype="object", header=0)

    if df.empty:
        return {
            "stats_areas": [],
            "message": "公式の統計分野一覧（statsfield.csv）が見つかりません。",
        }

    # Expected columns: NO, 大分類, 大分類コード, 小分類, 小分類コード
    if "大分類コード" not in df.columns:
        return {"stats_areas": [], "message": "statsfield.csv の形式が想定と異なります。"}

    # Build list of top-level (大分類) with sub_categories (小分類)
    areas: list[dict] = []
    for code, group in df.groupby("大分類コード", sort=True):
        code = str(code).strip()
        main_name = group["大分類"].iloc[0] if "大分類" in group.columns else ""
        sub_cats = []
        if "小分類コード" in group.columns and "小分類" in group.columns:
            for _, row in group.iterrows():
                sub_cats.append({
                    "code": str(row.get("小分類コード", "")).strip(),
                    "name": str(row.get("小分類", "")).strip(),
                })
        areas.append({
            "code": code,
            "name": main_name,
            "sub_categories": sub_cats,
        })

    return {
        "stats_areas": areas,
        "message": f"統計分野は大分類 {len(areas)} 件です。discover_datasets の stats_field に大分類コード（例: 02=人口・世帯）を指定して検索できます。",
    }


# Filename pattern: {year}_list_of_statsDataIds.csv
_CATALOG_PATTERN = re.compile(r"^(\d{4})_list_of_statsDataIds\.csv$")

# Consolidated catalog: single file for efficient lookups
_CATALOG_FULL_NAME = "catalog_full.parquet"


def _get_consolidated_path(lang: str, processed_dir: Path | None) -> Path | None:
    """Return path to consolidated catalog if it exists."""
    dirs = get_data_dirs()
    base = processed_dir if processed_dir is not None else dirs["processed"]
    path = base / lang / _CATALOG_FULL_NAME
    return path if path.exists() else None


def list_available_years(
    lang: str = "J",
    processed_dir: Path | str | None = None,
    timeout_seconds: float = DEFAULT_CATALOG_TIMEOUT_SECONDS,
) -> dict:
    """
    List years for which a catalog exists locally (so discover_datasets can be used).
    Prefers consolidated catalog_full.parquet when present; else scans listOfStatsFields/.
    timeout_seconds: max time for I/O; on timeout returns error dict with timeout=True.
    Returns dict with years (sorted), lang, and optional per-year dataset_count.
    """
    timeout_error = {"years": [], "lang": lang, "summary": [], "message": f"操作がタイムアウトしました。（{timeout_seconds:.0f}秒）", "timeout": True}

    def _body() -> dict:
        dirs = get_data_dirs()
        base = Path(processed_dir) if processed_dir else dirs["processed"]
        consolidated = _get_consolidated_path(lang, base)
        if consolidated is not None:
            try:
                df = pd.read_parquet(consolidated, columns=["surveyYears", "statsDataId"])
                if df.empty or "surveyYears" not in df.columns:
                    years_found = []
                    summary = []
                else:
                    df["surveyYears"] = df["surveyYears"].astype(str)
                    counts = df.groupby("surveyYears")["statsDataId"].nunique().sort_index()
                    years_found = counts.index.tolist()
                    summary = [{"year": y, "dataset_count": int(n)} for y, n in counts.items()]
                return {
                    "years": years_found,
                    "lang": lang,
                    "summary": summary,
                    "message": f"検索可能な年: {', '.join(years_found)}。各年について discover_datasets でデータセットを検索できます。" if years_found else "カタログが空です。",
                }
            except Exception:
                pass

        catalog_dir = base / lang / "listOfStatsFields"
        if not catalog_dir.exists():
            return {"years": [], "lang": lang, "summary": [], "message": "No catalog directory found."}

        years_found = []
        summary = []
        for p in catalog_dir.iterdir():
            if not p.is_file():
                continue
            m = _CATALOG_PATTERN.match(p.name)
            if m:
                year = m.group(1)
                years_found.append(year)
                try:
                    df = pd.read_csv(p, dtype="object", header=0)
                    n = len(df.drop_duplicates(subset=["statsDataId"]) if "statsDataId" in df.columns else df)
                    summary.append({"year": year, "dataset_count": n})
                except Exception:
                    summary.append({"year": year, "dataset_count": None})

        years_found.sort()
        summary.sort(key=lambda x: x["year"])
        return {
            "years": years_found,
            "lang": lang,
            "summary": summary,
            "message": f"検索可能な年: {', '.join(years_found)}。各年について discover_datasets でデータセットを検索できます。" if years_found else "カタログがまだありません。scripts/run_list_tables.py で取得し、scripts/run_build_catalog.py で統合カタログを生成してください。",
        }

    return _run_with_timeout(timeout_seconds, _body, timeout_error)


# Columns that can be used for aggregation (group-by). Must exist in catalog parquet.
_AGGREGATE_BY_ALLOWED = frozenset({
    "statsField",
    "gov_org_code",
    "gov_org_name",
    "sub_category_code",
    "sub_category_name",
    "statistics_name",
    "stat_name_code",
    "surveyYears",
})


def catalog_aggregate(
    by: str,
    year: str | None = None,
    filter_column: str | None = None,
    filter_value: str | None = None,
    lang: str = "J",
    limit: int = 50,
    include_display_name: bool = True,
    processed_dir: Path | str | None = None,
    timeout_seconds: float = DEFAULT_CATALOG_TIMEOUT_SECONDS,
) -> dict:
    """
    Aggregate catalog by a single attribute: group by `by` and count datasets (statsDataId).
    When year is set, uses the same discover path as search_catalog (load_catalog via _get_catalog_df)
    then aggregates over that DataFrame (discover then aggregate). When year is None, uses
    _load_full_catalog with predicate pushdown.
    timeout_seconds: max time for I/O and aggregation; on timeout returns error dict with timeout=True.
    by: one of statsField, gov_org_code, gov_org_name, sub_category_code, sub_category_name,
        statistics_name, stat_name_code, surveyYears.
    year: if set, only rows with surveyYears == year (predicate pushdown).
    filter_column, filter_value: if set, only rows where filter_column == filter_value (predicate pushdown).
    include_display_name: when by is a code column, try to add a name (e.g. from statsfield.csv for statsField).
    Returns by, year, filter_column, filter_value, lang, groups (list of {value, dataset_count, name?}), message.
    """
    by = str(by).strip()
    if by not in _AGGREGATE_BY_ALLOWED:
        return {
            "by": by,
            "year": year,
            "lang": lang,
            "groups": [],
            "message": f"by は次のいずれかにしてください: {', '.join(sorted(_AGGREGATE_BY_ALLOWED))}",
        }
    # Optional display name column (e.g. gov_org_name when by=gov_org_code)
    name_col = None
    if include_display_name:
        if by == "gov_org_code":
            name_col = "gov_org_name"
        elif by == "sub_category_code":
            name_col = "sub_category_name"

    timeout_error = {
        "by": by,
        "year": year,
        "filter_column": filter_column,
        "filter_value": filter_value,
        "lang": lang,
        "groups": [],
        "message": f"操作がタイムアウトしました。（{timeout_seconds:.0f}秒）",
        "timeout": True,
    }

    def _body() -> dict:
        # When year is set, use discover path (load_catalog via _get_catalog_df) then aggregate.
        # When year is None, use _load_full_catalog with predicate pushdown.
        if year is not None and str(year).strip():
            df = _get_catalog_df(
                year=str(year),
                lang=lang,
                filter_column=filter_column,
                filter_value=filter_value,
                processed_dir=processed_dir,
            )
            if not df.empty:
                cols = [c for c in [by, "statsDataId"] + ([name_col] if name_col and name_col in df.columns else []) if c in df.columns]
                df = df[cols].copy()
        else:
            cols = [by, "statsDataId"]
            if filter_column and filter_column not in cols:
                cols.append(filter_column)
            if filter_column and filter_column == "surveyYears":
                if "surveyYears" not in cols:
                    cols.append("surveyYears")
            if name_col and name_col not in cols:
                cols.append(name_col)
            filters: list[tuple[str, str, str | int]] = []
            if filter_column and filter_value is not None and str(filter_value).strip():
                filters.append((filter_column, "==", str(filter_value).strip()))
            df = _load_full_catalog(
                lang=lang,
                processed_dir=processed_dir,
                columns=cols,
                filters=filters if filters else None,
            )
        if df.empty:
            return {
                "by": by,
                "year": year,
                "filter_column": filter_column,
                "filter_value": filter_value,
                "lang": lang,
                "groups": [],
                "message": "カタログがありません。run_build_catalog を実行してください。" if not year else "該当するデータがありません。",
            }
        if by not in df.columns:
            return {"by": by, "year": year, "lang": lang, "groups": [], "message": f"列 '{by}' がありません。"}
        agg_dict = {"dataset_count": ("statsDataId", "nunique")} if "statsDataId" in df.columns else {"dataset_count": (by, "count")}
        if name_col and name_col in df.columns and name_col != by:
            agg_dict["_name"] = (name_col, "first")
        counts = df.groupby(by, dropna=False).agg(**agg_dict).reset_index()
        counts = counts.sort_values("dataset_count", ascending=False).head(limit)
        values = counts[by].map(lambda x: "" if pd.isna(x) else str(x))
        cnts = counts["dataset_count"].astype(int)
        names = (
            counts["_name"].map(lambda x: "" if pd.isna(x) else str(x))
            if "_name" in counts.columns
            else values
        )
        groups = [
            {"value": v, "dataset_count": c, "name": n or v}
            for v, c, n in zip(values, cnts, names)
        ]
        if by == "statsField" and include_display_name:
            code_to_name = _get_stats_field_code_to_name()
            for g in groups:
                g["name"] = code_to_name.get(g["value"], g.get("name", g["value"]))
        total = sum(g["dataset_count"] for g in groups)
        msg = f"by={by}: {len(groups)} 件、データセット合計 {total} 件。"
        if year:
            msg += f"（{year}年）"
        if filter_column and filter_value:
            msg += f" 条件: {filter_column}={filter_value}"
        return {
            "by": by,
            "year": year,
            "filter_column": filter_column,
            "filter_value": filter_value,
            "lang": lang,
            "groups": groups,
            "message": msg,
        }

    return _run_with_timeout(timeout_seconds, _body, timeout_error)


@functools.lru_cache(maxsize=16)
def _read_parquet_cached(
    path_str: str,
    mtime_ns: int,
    columns_key: tuple[str, ...] | None,
    filters_key: tuple[tuple[str, str, str | int], ...] | None,
) -> pd.DataFrame:
    """Cached parquet read; key includes mtime so rebuilt catalog invalidates cache."""
    path = Path(path_str)
    if not path.exists() or path.stat().st_mtime_ns != mtime_ns:
        return pd.DataFrame()
    try:
        cols = list(columns_key) if columns_key else None
        filts = list(filters_key) if filters_key else None
        return pd.read_parquet(path, columns=cols, filters=filts)
    except Exception:
        return pd.DataFrame()


def _load_full_catalog(
    lang: str = "J",
    processed_dir: Path | str | None = None,
    columns: list[str] | None = None,
    filters: list[tuple[str, str, str | int]] | None = None,
) -> pd.DataFrame:
    """Read the consolidated catalog parquet into a DataFrame. Optional columns and filters. Cached by path+mtime+columns+filters."""
    base = Path(processed_dir) if processed_dir else get_data_dirs()["processed"]
    consolidated = _get_consolidated_path(lang, base)
    if consolidated is None or not consolidated.exists():
        return pd.DataFrame()
    mtime_ns = consolidated.stat().st_mtime_ns
    columns_key = tuple(sorted(columns)) if columns else None
    filters_key = tuple(tuple(f) for f in filters) if filters else None
    return _read_parquet_cached(str(consolidated), mtime_ns, columns_key, filters_key)


def load_catalog(
    year: str,
    lang: str = "J",
    processed_dir: Path | str | None = None,
) -> pd.DataFrame:
    """
    Load the catalog for a given year and lang.
    Prefers consolidated catalog_full.parquet when present (reads only that year via predicate pushdown);
    else loads per-year CSV from listOfStatsFields/.
    Returns empty DataFrame if not found.
    """
    dirs = get_data_dirs()
    base = Path(processed_dir) if processed_dir else dirs["processed"]

    # Prefer consolidated catalog: read only rows for this year (predicate pushdown)
    consolidated = _get_consolidated_path(lang, base)
    if consolidated is not None:
        try:
            df = pd.read_parquet(
                consolidated,
                filters=[("surveyYears", "==", str(year))],
            )
            if not df.empty and "surveyYears" in df.columns:
                return df
            return pd.DataFrame()
        except Exception:
            try:
                # Fallback if engine doesn't support filters: read all then filter
                df = pd.read_parquet(consolidated)
                if not df.empty and "surveyYears" in df.columns:
                    return df[df["surveyYears"].astype(str) == str(year)].copy()
            except Exception:
                pass
            return pd.DataFrame()

    # Fallback: per-year CSV
    path = base / lang / "listOfStatsFields" / f"{year}_list_of_statsDataIds.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype="object", header=0)


def _get_catalog_df(
    year: str,
    lang: str = "J",
    stats_field: str | None = None,
    keyword: str | None = None,
    filter_column: str | None = None,
    filter_value: str | None = None,
    processed_dir: Path | str | None = None,
) -> pd.DataFrame:
    """
    Shared discover path: load catalog for one year (load_catalog) then apply optional filters.
    Used by search_catalog (discover → head(limit) → list[dict]) and catalog_aggregate (discover → aggregate).
    """
    df = load_catalog(year=year, lang=lang, processed_dir=processed_dir)
    if df.empty:
        return df

    if stats_field is not None and str(stats_field).strip() != "":
        if "statsField" in df.columns:
            df = df[df["statsField"].astype(str).str.strip() == str(stats_field).strip()].copy()
        else:
            return pd.DataFrame()

    if keyword is not None and keyword.strip() != "":
        kw = keyword.strip().lower()
        text_cols = [
            c for c in ["statistics_name", "main_category_name", "sub_category_name", "gov_org_name", "title_spec_name"]
            if c in df.columns
        ]
        if text_cols:
            mask = pd.Series(False, index=df.index)
            for c in text_cols:
                mask = mask | df[c].fillna("").astype(str).str.lower().str.contains(kw, regex=False)
            df = df[mask].copy()

    if filter_column and filter_value is not None and str(filter_value).strip() and filter_column in df.columns:
        df = df[df[filter_column].astype(str).str.strip() == str(filter_value).strip()].copy()

    return df


def catalog_overview(
    lang: str = "J",
    year: str | None = None,
    include_stats_areas: bool = False,
    processed_dir: Path | str | None = None,
    timeout_seconds: float = DEFAULT_CATALOG_TIMEOUT_SECONDS,
) -> dict:
    """
    Single entry point for catalog lookup: years, dataset counts, and optionally stats fields per year or master stats areas.
    Use when the user asks "何年分のデータが検索できる？", "2024年の統計分野全て", or "overview of what's available".
    timeout_seconds: max time for I/O; on timeout returns error dict with timeout=True.
    - year=None: returns years (sorted) and dataset_count per year; optionally stats_areas from statsfield.csv.
    - year set: returns years_available (context), and for that year: stats_fields with dataset_count and names; optionally stats_areas.
    """
    timeout_error = {"lang": lang, "years": [], "summary": [], "message": f"操作がタイムアウトしました。（{timeout_seconds:.0f}秒）", "timeout": True}

    def _body() -> dict:
        base = Path(processed_dir) if processed_dir else get_data_dirs()["processed"]
        consolidated = _get_consolidated_path(lang, base)
        out: dict = {"lang": lang, "years": [], "summary": [], "message": ""}

        df = pd.DataFrame()
        if consolidated and consolidated.exists():
            try:
                df = pd.read_parquet(consolidated, columns=["surveyYears", "statsDataId", "statsField"])
            except Exception:
                pass

        if df.empty:
            catalog_dir = base / lang / "listOfStatsFields"
            if catalog_dir.exists():
                years_found = []
                for p in catalog_dir.iterdir():
                    m = _CATALOG_PATTERN.match(p.name) if p.is_file() else None
                    if m:
                        years_found.append(m.group(1))
                years_found.sort()
                if years_found:
                    out["years"] = years_found
                    out["summary"] = [{"year": y, "dataset_count": None} for y in years_found]
                    out["message"] = f"検索可能な年: {', '.join(years_found)}。（catalog_full.parquet が未作成のため件数は不明。run_build_catalog を実行してください。）"

        if not df.empty and "surveyYears" in df.columns:
            df["surveyYears"] = df["surveyYears"].astype(str)
            counts = df.groupby("surveyYears")["statsDataId"].nunique().sort_index()
            years_found = counts.index.tolist()
            out["years"] = years_found
            out["summary"] = [{"year": y, "dataset_count": int(n)} for y, n in counts.items()]
            out["message"] = f"検索可能な年: {', '.join(years_found)}。"

        if year is not None and str(year).strip():
            df_year = load_catalog(year=str(year), lang=lang, processed_dir=processed_dir)
            if not df_year.empty and "statsField" in df_year.columns:
                counts = df_year["statsField"].astype(str).str.strip().value_counts(sort=False)
                stats_fields = [{"stats_field": k, "dataset_count": int(v)} for k, v in counts.items()]
                code_to_name = _get_stats_field_code_to_name()
                for s in stats_fields:
                    s["stats_field_name"] = code_to_name.get(s["stats_field"], "")
                out["year"] = str(year)
                out["stats_fields"] = stats_fields
                out["message"] = (out.get("message", "") + f" {year}年: 統計分野 {len(stats_fields)} 件。").strip()
            else:
                out["year"] = str(year)
                out["stats_fields"] = []
        else:
            out["stats_fields"] = []

        if include_stats_areas:
            areas_result = list_stats_areas()
            out["stats_areas"] = areas_result.get("stats_areas", [])
            out["message"] = (out.get("message", "") + " " + (areas_result.get("message", "") or "")).strip()
        else:
            out["stats_areas"] = []

        return out

    return _run_with_timeout(timeout_seconds, _body, timeout_error)


def list_stats_fields_for_year(
    year: str,
    lang: str = "J",
    processed_dir: Path | str | None = None,
    include_names: bool = True,
    timeout_seconds: float = DEFAULT_CATALOG_TIMEOUT_SECONDS,
) -> dict:
    """
    Return unique stats_field (大分類コード) for a given year with dataset counts.
    Fast: uses predicate pushdown when reading consolidated parquet (only that year).
    timeout_seconds: max time for I/O; on timeout returns error dict with timeout=True.
    Use when the user asks "2024年の統計分野全て" or "which stats fields have data in year X".
    include_names: if True, merge with statsfield.csv to add 大分類 names.
    """
    timeout_error = {"year": year, "lang": lang, "stats_fields": [], "message": f"操作がタイムアウトしました。（{timeout_seconds:.0f}秒）", "timeout": True}

    def _body() -> dict:
        df = load_catalog(year=year, lang=lang, processed_dir=processed_dir)
        if df.empty or "statsField" not in df.columns:
            return {
                "year": year,
                "lang": lang,
                "stats_fields": [],
                "message": "該当年のカタログがありません。" if df.empty else "statsField 列がありません。",
            }
        counts = df["statsField"].astype(str).str.strip().value_counts(sort=False)
        stats_fields = [{"stats_field": k, "dataset_count": int(v)} for k, v in counts.items()]
        if include_names:
            code_to_name = _get_stats_field_code_to_name()
            for s in stats_fields:
                s["stats_field_name"] = code_to_name.get(s["stats_field"], "")
        return {
            "year": year,
            "lang": lang,
            "stats_fields": stats_fields,
            "message": f"{year}年: 統計分野 {len(stats_fields)} 件（データセット合計 {counts.sum()} 件）。",
        }

    return _run_with_timeout(timeout_seconds, _body, timeout_error)


def stats_field_subcategories(
    stats_field: str,
    year: str | None = None,
    lang: str = "J",
    processed_dir: Path | str | None = None,
) -> dict:
    """
    Within a 大分類 (stats_field), return dataset counts broken down by 小分類 (sub_category).
    Delegates to catalog_aggregate(by="sub_category_code", filter_column="statsField", filter_value=stats_field).
    """
    stats_field = str(stats_field).strip()
    out = catalog_aggregate(
        by="sub_category_code",
        year=year,
        filter_column="statsField",
        filter_value=stats_field,
        lang=lang,
        limit=100,
        include_display_name=True,
        processed_dir=processed_dir,
    )
    groups = out.get("groups", [])
    subcategories = [{"sub_category_code": g["value"], "sub_category_name": g.get("name", g["value"]), "dataset_count": g["dataset_count"]} for g in groups]
    # Use cached mapping
    code_to_name = _get_stats_field_code_to_name()
    return {
        "stats_field": stats_field,
        "stats_field_name": code_to_name.get(stats_field, ""),
        "year": out.get("year"),
        "lang": out.get("lang"),
        "subcategories": subcategories,
        "message": out.get("message", ""),
    }


def list_datasets_by_gov_org(
    year: str | None = None,
    lang: str = "J",
    limit: int = 50,
    gov_org_code: str | None = None,
    gov_org_name: str | None = None,
    processed_dir: Path | str | None = None,
) -> dict:
    """
    Aggregate dataset counts by government organization (府省).
    Use when the user asks for datasets by ministry (e.g. 総務省, 厚生労働省).
    year: if set, limit to that year; otherwise use all years.
    gov_org_code or gov_org_name: if set, only load rows for that org (predicate pushdown — much faster).
    """
    fcol = "gov_org_code" if (gov_org_code and str(gov_org_code).strip()) else "gov_org_name"
    fval = str(gov_org_code or gov_org_name or "").strip() or None
    out = catalog_aggregate(
        by="gov_org_code",
        year=year,
        filter_column=fcol if fval else None,
        filter_value=fval,
        lang=lang,
        limit=limit,
        include_display_name=True,
        processed_dir=processed_dir,
    )
    groups = out.get("groups", [])
    gov_orgs = [{"gov_org_code": g["value"], "gov_org_name": g.get("name", g["value"]), "dataset_count": g["dataset_count"]} for g in groups]
    if fcol == "gov_org_name" and gov_orgs:
        gov_orgs[0]["gov_org_code"] = ""
    return {"year": out.get("year"), "lang": out.get("lang"), "gov_orgs": gov_orgs, "message": out.get("message", "")}


def time_series_discovery(
    year_start: str | None = None,
    year_end: str | None = None,
    lang: str = "J",
    min_years: int = 2,
    limit: int = 50,
    processed_dir: Path | str | None = None,
    timeout_seconds: float = DEFAULT_CATALOG_TIMEOUT_SECONDS,
) -> dict:
    """
    Find statistics that exist across multiple years (e.g. same statistics_name in 2020–2024).
    Use when the user asks "which statistics are available annually?" or "same stats 2020 to 2024".
    timeout_seconds: max time for I/O; on timeout returns error dict with timeout=True.
    year_start, year_end: optional range; if both set, only consider years in [year_start, year_end].
    min_years: include only statistics that appear in at least this many years (default 2).
    """
    timeout_error = {"year_start": year_start, "year_end": year_end, "lang": lang, "statistics": [], "message": f"操作がタイムアウトしました。（{timeout_seconds:.0f}秒）", "timeout": True}

    def _body() -> dict:
        df = _load_full_catalog(
            lang=lang,
            processed_dir=processed_dir,
            columns=["statistics_name", "stat_name_code", "surveyYears", "statsDataId"],
        )
        if df.empty or "statistics_name" not in df.columns or "surveyYears" not in df.columns:
            return {
                "year_start": year_start,
                "year_end": year_end,
                "lang": lang,
                "statistics": [],
                "message": "カタログがありません。run_build_catalog を実行してください。" if df.empty else "statistics_name または surveyYears がありません。",
            }
        if year_start is not None and str(year_start).strip():
            df = df[df["surveyYears"].astype(str) >= str(year_start)]
        if year_end is not None and str(year_end).strip():
            df = df[df["surveyYears"].astype(str) <= str(year_end)]
        if df.empty:
            return {"year_start": year_start, "year_end": year_end, "lang": lang, "statistics": [], "message": "該当する年のデータがありません。"}
        key = "stat_name_code" if "stat_name_code" in df.columns and df["stat_name_code"].notna().any() else "statistics_name"
        df = df.dropna(subset=[key])
        if df.empty:
            return {"year_start": year_start, "year_end": year_end, "lang": lang, "statistics": [], "message": "統計名でグループ化できるデータがありません。"}
        grouped = df.groupby(key)
        years_per_stat = grouped["surveyYears"].apply(lambda s: sorted(s.astype(str).unique().tolist())).to_dict()
        name_per_key = grouped["statistics_name"].first().to_dict() if "statistics_name" in df.columns else {k: k for k in years_per_stat}
        candidates = [(k, years_per_stat[k], name_per_key.get(k, k)) for k in years_per_stat if len(years_per_stat[k]) >= min_years]
        candidates.sort(key=lambda x: -len(x[1]))
        statistics = []
        for k, years, name in candidates[:limit]:
            statistics.append({
                "statistics_name": name,
                "stat_name_code": k if key == "stat_name_code" else None,
                "years": years,
                "year_count": len(years),
            })
        return {
            "year_start": year_start,
            "year_end": year_end,
            "lang": lang,
            "statistics": statistics,
            "message": f"複数年にわたる統計: {len(statistics)} 件（最低 {min_years} 年）。" + (f" 対象年: {year_start}–{year_end}" if year_start and year_end else ""),
        }

    return _run_with_timeout(timeout_seconds, _body, timeout_error)


def search_catalog(
    year: str,
    lang: str = "J",
    stats_field: str | None = None,
    keyword: str | None = None,
    limit: int = 20,
    processed_dir: Path | str | None = None,
    timeout_seconds: float = DEFAULT_CATALOG_TIMEOUT_SECONDS,
) -> list[dict]:
    """
    Search the catalog by year, optional statsField, and optional keyword.
    Keyword is matched (case-insensitive) against statistics_name, main_category_name,
    sub_category_name, gov_org_name, title_spec_name.
    timeout_seconds: max time for I/O; on timeout returns [{error: "timeout", message: "..."}].
    Returns a list of dicts with statsDataId, statistics_name, main_category_name,
    sub_category_name, gov_org_name, statsField, surveyYears (limit items).
    Uses _get_catalog_df (discover path) then head(limit) → list[dict].
    """

    def _body() -> list[dict]:
        df = _get_catalog_df(
            year=year,
            lang=lang,
            stats_field=stats_field,
            keyword=keyword,
            processed_dir=processed_dir,
        )
        if df.empty:
            return []
        cols = ["statsDataId", "statistics_name", "main_category_name", "sub_category_name", "gov_org_name", "statsField", "surveyYears"]
        cols = [c for c in cols if c in df.columns]
        if not cols:
            return []
        df = df[cols].drop_duplicates(subset=["statsDataId"] if "statsDataId" in cols else cols[0:1])
        df = df.head(limit)
        return df.to_dict(orient="records")

    timeout_result = [{"error": "timeout", "message": f"操作がタイムアウトしました。（{timeout_seconds:.0f}秒）"}]
    return _run_with_timeout(timeout_seconds, _body, timeout_result)


def get_dataset_metadata(
    stats_data_id: str,
    year: str,
    lang: str = "J",
    processed_dir: Path | str | None = None,
    timeout_seconds: float = DEFAULT_CATALOG_TIMEOUT_SECONDS,
) -> dict:
    """
    Return detailed dataset metadata from the catalog: survey frequency (月次/年次),
    last updated, data period, plus statistics_name, title, gov_org_name when present.
    Uses catalog_full.parquet or per-year listOfStatsFields; returns empty metadata
    if the dataset is not in the catalog.
    timeout_seconds: max time for I/O; on timeout returns {error, message, timeout: True}.
    """
    sid = str(stats_data_id).strip()
    y = str(year).strip()
    timeout_error = {
        "stats_data_id": sid,
        "year": y,
        "lang": lang,
        "survey_frequency": None,
        "last_updated": None,
        "data_period": None,
        "statistics_name": None,
        "title": None,
        "gov_org_name": None,
        "message": f"操作がタイムアウトしました。（{timeout_seconds:.0f}秒）",
        "timeout": True,
    }

    def _body() -> dict:
        df = load_catalog(year=y, lang=lang, processed_dir=processed_dir)
        if df.empty:
            return {
                "stats_data_id": sid,
                "year": y,
                "lang": lang,
                "survey_frequency": None,
                "last_updated": None,
                "data_period": None,
                "statistics_name": None,
                "title": None,
                "gov_org_name": None,
                "message": "該当するデータセットがカタログにありません。",
            }
        match = df[df["statsDataId"].astype(str).str.strip() == sid]
        if match.empty:
            return {
                "stats_data_id": sid,
                "year": y,
                "lang": lang,
                "survey_frequency": None,
                "last_updated": None,
                "data_period": None,
                "statistics_name": None,
                "title": None,
                "gov_org_name": None,
                "message": "該当するデータセットがカタログにありません。",
            }
        row = match.iloc[0]
        def _cell(c: str):
            if c not in row.index:
                return None
            v = row[c]
            if v is None or (isinstance(v, float) and v != v):
                return None
            return str(v).strip() or None

        return {
            "stats_data_id": sid,
            "year": y,
            "lang": lang,
            "survey_frequency": _cell("cycle"),
            "last_updated": _cell("updated_date"),
            "data_period": _cell("survey_date"),
            "statistics_name": _cell("statistics_name") if "statistics_name" in row.index else _cell("stat_name_name"),
            "title": _cell("title"),
            "gov_org_name": _cell("gov_org_name"),
            "open_date": _cell("open_date"),
            "message": None,
        }

    return _run_with_timeout(timeout_seconds, _body, timeout_error)
