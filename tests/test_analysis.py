"""Tests for basic analysis (4-2): summary, filter, aggregate, time_series, top_bottom."""

import importlib.util
import sys
from pathlib import Path

# Load run_analysis directly from repo so tests pass regardless of package install/path
_root = Path(__file__).resolve().parent.parent
_run_analysis_py = _root / "kumonjo" / "analysis" / "run_analysis.py"
_spec = importlib.util.spec_from_file_location("kumonjo.analysis.run_analysis", _run_analysis_py)
_mod = importlib.util.module_from_spec(_spec)
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
_spec.loader.exec_module(_mod)
run_analysis = _mod.run_analysis

import pytest


def _table(rows: list[dict], columns: list[str] | None = None) -> tuple[list[str], list[dict]]:
    if columns is None and rows:
        columns = list(rows[0].keys())
    return columns or [], rows


def test_summary():

    cols = ["area_name", "value"]
    rows = [
        {"area_name": "東京都", "value": 100},
        {"area_name": "大阪府", "value": 80},
        {"area_name": "福岡県", "value": 60},
    ]
    out = run_analysis(cols, rows, "summary", value_column="value")
    assert out["type"] == "summary"
    r = out["result"]
    assert r["count"] == 3
    assert r["mean"] == 80.0
    assert r["min"] == 60
    assert r["max"] == 100
    assert r["sum"] == 240


def test_summary_coerces_numeric():
    cols = ["value"]
    rows = [{"value": "10"}, {"value": "20"}, {"value": "-"}]
    out = run_analysis(cols, rows, "summary", value_column="value")
    assert out["result"]["count"] == 2
    assert out["meta"]["null_count"] == 1


def test_filter():
    cols = ["area_name", "value"]
    rows = [
        {"area_name": "東京都", "value": 100},
        {"area_name": "大阪府", "value": 80},
        {"area_name": "東京都", "value": 90},
    ]
    out = run_analysis(
        cols, rows, "filter", filter_column="area_name", filter_value="東京都"
    )
    assert out["type"] == "filter"
    assert out["result"]["row_count"] == 2
    assert all(r["area_name"] == "東京都" for r in out["result"]["rows"])


def test_filter_values():
    cols = ["area_name", "value"]
    rows = [
        {"area_name": "東京都", "value": 100},
        {"area_name": "大阪府", "value": 80},
        {"area_name": "福岡県", "value": 60},
    ]
    out = run_analysis(
        cols, rows, "filter", filter_column="area_name", filter_values=["東京都", "福岡県"]
    )
    assert out["result"]["row_count"] == 2
    names = {r["area_name"] for r in out["result"]["rows"]}
    assert names == {"東京都", "福岡県"}


def test_aggregate():
    cols = ["area_name", "value"]
    rows = [
        {"area_name": "東京都", "value": 100},
        {"area_name": "東京都", "value": 50},
        {"area_name": "大阪府", "value": 80},
    ]
    out = run_analysis(
        cols, rows, "aggregate",
        value_column="value", group_by=["area_name"], agg="sum",
    )
    assert out["type"] == "aggregate"
    groups = {r["area_name"]: r["value"] for r in out["result"]["groups"]}
    assert groups["東京都"] == 150
    assert groups["大阪府"] == 80


def test_time_series():
    cols = ["time_name", "value"]
    rows = [
        {"time_name": "2020", "value": 100},
        {"time_name": "2021", "value": 110},
        {"time_name": "2020", "value": 10},
    ]
    out = run_analysis(cols, rows, "time_series", value_column="value")
    assert out["type"] == "time_series"
    points = {p["time"]: p["value"] for p in out["result"]["points"]}
    assert points["2020"] == 110
    assert points["2021"] == 110


def test_time_series_explicit_column():
    cols = ["year", "value"]
    rows = [{"year": "2022", "value": 5}, {"year": "2023", "value": 6}]
    out = run_analysis(cols, rows, "time_series", value_column="value", time_column="year")
    assert out["result"]["row_count"] == 2
    assert out["result"]["time_column"] == "year"


def test_top_bottom():
    cols = ["area_name", "value"]
    rows = [
        {"area_name": "A", "value": 10},
        {"area_name": "B", "value": 30},
        {"area_name": "C", "value": 20},
    ]
    out = run_analysis(cols, rows, "top_bottom", value_column="value", n=2, order="top")
    assert out["result"]["row_count"] == 2
    vals = [r["value"] for r in out["result"]["rows"]]
    assert vals == [30, 20]

    out2 = run_analysis(cols, rows, "top_bottom", value_column="value", n=2, order="bottom")
    vals2 = [r["value"] for r in out2["result"]["rows"]]
    assert vals2 == [10, 20]


def test_empty_table():
    out = run_analysis(columns=["a", "value"], rows=[], analysis_type="summary")
    assert out["type"] == "summary"
    assert out["result"] == {}
    assert "empty" in out.get("warnings", [""])[0].lower()


def test_unknown_analysis_type():
    out = run_analysis(columns=["value"], rows=[{"value": 1}], analysis_type="unknown")
    assert out["type"] == "unknown"
    assert "Unknown" in (out.get("warnings") or [""])[0]
