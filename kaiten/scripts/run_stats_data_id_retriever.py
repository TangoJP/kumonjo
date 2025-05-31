import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

import pandas as pd
from core.retrievers.core_retriever import BaseRetriever
from core.retrievers.stats_data_id_retriever import MultiStatsFieldTableFetcher

PATH_LIST_OF_STATS_DATA_IDS = os.path.join("data", "official", "statsfield.csv")

if __name__ == "__main__":
    df_statsfields = pd.read_csv(PATH_LIST_OF_STATS_DATA_IDS, dtype="object", header=0)
    list_of_stats_data_ids = sorted(df_statsfields["大分類コード"].unique())

    args = BaseRetriever.parse_args()

    fetcher = MultiStatsFieldTableFetcher(
        api_key=args.api_key,
        year=args.year,
        statsFields=list_of_stats_data_ids,
        lang="J",
        output_dir_raw="data/raw",
        output_dir_processed="data/processed"
    )

    fetcher.run()

    # retriever = StatsFieldTableRetriever(api_key=args.api_key)

    # retriever.run()

