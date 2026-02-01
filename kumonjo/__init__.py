"""Kumonjo: government data retrieval and processing for e-Stat (Japan)."""

from kumonjo.config import get_api_key, get_data_dirs
from kumonjo.retrieval.list_tables import fetch_list_of_tables
from kumonjo.retrieval.get_table import fetch_table

__all__ = [
    "get_api_key",
    "get_data_dirs",
    "fetch_list_of_tables",
    "fetch_table",
]
