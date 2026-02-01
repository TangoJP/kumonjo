"""Load and search the listOfStatsFields catalog (dataset discovery)."""

import re
from pathlib import Path

import pandas as pd

from kumonjo.config import get_data_dirs


def list_stats_areas(official_dir: Path | str | None = None) -> dict:
    """
    List all stats areas (大分類・小分類) from the official statsfield.csv.
    Use when the user asks "list of all stats areas" or "どの統計分野がある？".
    Returns dict with stats_areas (list of {code, name, sub_categories}), and message.
    """
    dirs = get_data_dirs()
    base = Path(official_dir) if official_dir else dirs["official"]
    path = base / "statsfield.csv"
    if not path.exists():
        return {
            "stats_areas": [],
            "message": "公式の統計分野一覧（statsfield.csv）が見つかりません。",
        }

    df = pd.read_csv(path, dtype="object", header=0)
    # Expected columns: NO, 大分類, 大分類コード, 小分類, 小分類コード
    if df.empty or "大分類コード" not in df.columns:
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
) -> dict:
    """
    List years for which a catalog exists locally (so discover_datasets can be used).
    Prefers consolidated catalog_full.parquet when present; else scans listOfStatsFields/.
    Returns dict with years (sorted), lang, and optional per-year dataset_count.
    """
    dirs = get_data_dirs()
    base = Path(processed_dir) if processed_dir else dirs["processed"]

    # Prefer consolidated catalog: read only columns needed for years + counts (less I/O)
    consolidated = _get_consolidated_path(lang, base)
    if consolidated is not None:
        try:
            df = pd.read_parquet(consolidated, columns=["surveyYears", "statsDataId"])
            if df.empty or "surveyYears" not in df.columns:
                years_found = []
                summary = []
            else:
                years_found = sorted(df["surveyYears"].astype(str).unique().tolist())
                summary = []
                for y in years_found:
                    sub = df[df["surveyYears"].astype(str) == y]
                    n = len(sub.drop_duplicates(subset=["statsDataId"]) if "statsDataId" in sub.columns else sub)
                    summary.append({"year": y, "dataset_count": n})
            return {
                "years": years_found,
                "lang": lang,
                "summary": summary,
                "message": f"検索可能な年: {', '.join(years_found)}。各年について discover_datasets でデータセットを検索できます。" if years_found else "カタログが空です。",
            }
        except Exception:
            pass

    # Fallback: scan per-year CSV files
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


def catalog_overview(
    lang: str = "J",
    year: str | None = None,
    include_stats_areas: bool = False,
    processed_dir: Path | str | None = None,
) -> dict:
    """
    Single entry point for catalog lookup: years, dataset counts, and optionally stats fields per year or master stats areas.
    Use when the user asks "何年分のデータが検索できる？", "2024年の統計分野全て", or "overview of what's available".
    - year=None: returns years (sorted) and dataset_count per year; optionally stats_areas from statsfield.csv.
    - year set: returns years_available (context), and for that year: stats_fields with dataset_count and names; optionally stats_areas.
    """
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
        # Fallback: years from listOfStatsFields filenames
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
        years_found = sorted(df["surveyYears"].astype(str).unique().tolist())
        out["years"] = years_found
        summary = []
        for y in years_found:
            sub = df[df["surveyYears"].astype(str) == y]
            n = len(sub.drop_duplicates(subset=["statsDataId"]) if "statsDataId" in sub.columns else sub)
            summary.append({"year": y, "dataset_count": n})
        out["summary"] = summary
        out["message"] = f"検索可能な年: {', '.join(years_found)}。"

    if year is not None and str(year).strip():
        # Add stats_fields for this year (same as list_stats_fields_for_year)
        df_year = load_catalog(year=str(year), lang=lang, processed_dir=processed_dir)
        if not df_year.empty and "statsField" in df_year.columns:
            counts = df_year["statsField"].astype(str).str.strip().value_counts(sort=False)
            stats_fields = [{"stats_field": k, "dataset_count": int(v)} for k, v in counts.items()]
            areas = list_stats_areas()
            code_to_name = {a["code"]: a.get("name", "") for a in areas.get("stats_areas", [])}
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


def list_stats_fields_for_year(
    year: str,
    lang: str = "J",
    processed_dir: Path | str | None = None,
    include_names: bool = True,
) -> dict:
    """
    Return unique stats_field (大分類コード) for a given year with dataset counts.
    Fast: uses predicate pushdown when reading consolidated parquet (only that year).
    Use when the user asks "2024年の統計分野全て" or "which stats fields have data in year X".
    include_names: if True, merge with statsfield.csv to add 大分類 names.
    """
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
        areas = list_stats_areas()
        code_to_name = {}
        for a in areas.get("stats_areas", []):
            code_to_name[a["code"]] = a.get("name", "")
        for s in stats_fields:
            s["stats_field_name"] = code_to_name.get(s["stats_field"], "")

    return {
        "year": year,
        "lang": lang,
        "stats_fields": stats_fields,
        "message": f"{year}年: 統計分野 {len(stats_fields)} 件（データセット合計 {counts.sum()} 件）。",
    }


def search_catalog(
    year: str,
    lang: str = "J",
    stats_field: str | None = None,
    keyword: str | None = None,
    limit: int = 20,
    processed_dir: Path | str | None = None,
) -> list[dict]:
    """
    Search the catalog by year, optional statsField, and optional keyword.
    Keyword is matched (case-insensitive) against statistics_name, main_category_name,
    sub_category_name, gov_org_name, title_spec_name.
    Returns a list of dicts with statsDataId, statistics_name, main_category_name,
    sub_category_name, gov_org_name, statsField, surveyYears (limit items).
    """
    df = load_catalog(year=year, lang=lang, processed_dir=processed_dir)
    if df.empty:
        return []

    if stats_field is not None and stats_field != "":
        if "statsField" in df.columns:
            df = df[df["statsField"].astype(str).str.strip() == str(stats_field).strip()]
        else:
            df = pd.DataFrame()

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
            df = df[mask]

    cols = ["statsDataId", "statistics_name", "main_category_name", "sub_category_name", "gov_org_name", "statsField", "surveyYears"]
    cols = [c for c in cols if c in df.columns]
    if not cols:
        return []
    df = df[cols].drop_duplicates(subset=["statsDataId"] if "statsDataId" in cols else cols[0:1])
    df = df.head(limit)
    return df.to_dict(orient="records")
