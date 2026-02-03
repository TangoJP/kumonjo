"""Tests for detailed dataset metadata (3-3): survey frequency, last updated, data period."""

import pytest

from kumonjo.discovery.catalog import get_dataset_metadata
from kumonjo.processing.parse_response import extract_table_metadata


def test_extract_table_metadata_from_response():
    """extract_table_metadata parses getStatsData TABLE_INF into survey_frequency, last_updated, data_period."""
    # Simulate getStatsData response TABLE_INF (e-Stat uses $ for text values)
    resp = {
        "GET_STATS_DATA": {
            "STATISTICAL_DATA": {
                "TABLE_INF": {
                    "@id": "0002111847",
                    "CYCLE": {"$": "年次"},
                    "UPDATED_DATE": "20240301",
                    "SURVEY_DATE": "2023",
                    "STATISTICS_NAME": {"$": "人口推計"},
                    "TITLE": {"$": "人口推計 年齢別人口"},
                }
            }
        }
    }
    m = extract_table_metadata(resp)
    assert m["survey_frequency"] == "年次"
    assert m["last_updated"] == "20240301"
    assert m["data_period"] == "2023"
    assert m["statistics_name"] == "人口推計"
    assert m["title"] == "人口推計 年齢別人口"
    assert m["stats_data_id"] == "0002111847"


def test_extract_table_metadata_empty():
    """extract_table_metadata returns empty dict when TABLE_INF missing."""
    m = extract_table_metadata({})
    assert m["survey_frequency"] is None
    assert m["last_updated"] is None
    assert m["data_period"] is None


def test_get_dataset_metadata_not_in_catalog():
    """get_dataset_metadata returns message when dataset not in catalog."""
    r = get_dataset_metadata("0002111847", "2024", "J")
    assert r.get("survey_frequency") is None
    assert r.get("last_updated") is None
    assert r.get("data_period") is None
    assert "カタログ" in (r.get("message") or "")
