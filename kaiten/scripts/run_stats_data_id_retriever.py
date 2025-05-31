# ── kaiten/core/retrievers/run_statsfield_table_retriever.py ──

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

from core.retrievers.core_retriever import BaseRetriever
from core.retrievers.stats_data_id_retriever import StatsFieldTableRetriever


if __name__ == "__main__":
    args = BaseRetriever.parse_args()

    retriever = StatsFieldTableRetriever(api_key=args.api_key)

    retriever.run()
