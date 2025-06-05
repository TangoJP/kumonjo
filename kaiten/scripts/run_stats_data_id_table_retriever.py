import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PARENT_DIR)

import logging
import pandas as pd
from core.retrievers.stats_data_id_table_retriever import StatsDataIdTableRetriever
from core.argparser import EStatsArgParser

DIR_STATSFIELD = "data/processed"

if __name__ == "__main__":
    args = EStatsArgParser.parse_args()

    path_statsfield = os.path.join(
        DIR_STATSFIELD, 
        args.lang, 
        "listOfStatsFields",
        f"{args.year}_list_of_statsDataIds.csv"
    )
    df_statsfields = pd.read_csv(path_statsfield, dtype="object", header=0)
    list_of_stats_data_ids = \
        df_statsfields[df_statsfields["statsField"]==args.statsField]["statsDataId"].unique()
    list_of_stats_data_ids = sorted(list_of_stats_data_ids)
    num_stats_data_ids = len(list_of_stats_data_ids)
    num_stats_data_ids_successful = 0

    for id_ in list_of_stats_data_ids:
        fetcher = StatsDataIdTableRetriever(
            api_key=args.api_key,
            year=args.year,
            statsDataId=id_,
            lang="J",
            output_dir_raw="data/raw",
            output_dir_processed="data/processed",
            output_format='parquet'
        )
        try:
            fetcher.run()
            num_stats_data_ids_successful += 1
        except Exception as e:
            logging.info(f"Retrieving statsDataId={id_} failed: {e}")


    logging.info(f"{num_stats_data_ids_successful} statsDataId tables successfull retrieve ({num_stats_data_ids} attempted)")