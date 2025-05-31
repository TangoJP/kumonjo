# ── kaiten/core/retrievers/statsfield_table_retriever.py ──

import os
import sys

# We want “import base_retriever” to work when this file is run from proj_root.
# Insert the folder “.../kaiten/core/retrievers” into sys.path at runtime:
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import pandas as pd
from datetime import datetime
from core_retriever import BaseRetriever


class StatsFieldTableRetriever(BaseRetriever):

    def get_base_url(self) -> str:
        # Hard‐coded to the e-Stat “getStatsList” endpoint root:
        return "https://api.e-stat.go.jp/rest/3.0/app/json"

    def fetch(self, stats_data_ids: list, years: list, lang: str = "J") -> pd.DataFrame:
        outputs = []

        for code in stats_data_ids:
            for year in years:
                print(f"\nRetrieving tables for statsField={code} for year={year}")
                response = self.get(
                    endpoint="getStatsList",
                    params={"statsField": code, "surveyYears": year, "lang": lang},
                )

                number_of_tables = (
                    response
                    .get("GET_STATS_LIST", {})
                    .get("DATALIST_INF", {})
                    .get("NUMBER", 0)
                )
                if number_of_tables == 0:
                    print("→ Valid response, but no data available.")
                    continue

                table_list = response["GET_STATS_LIST"]["DATALIST_INF"]["TABLE_INF"]
                df = pd.DataFrame(table_list)
                df["retrieved_at"] = datetime.now()
                df["statsField"] = code
                df["surveyYears"] = year
                outputs.append(df)

        if not outputs:
            # Return an empty DataFrame if nothing was retrieved:
            return pd.DataFrame()

        return pd.concat(outputs, axis=0).reset_index(drop=True)

    def clean(self, df_tables: pd.DataFrame) -> pd.DataFrame:

        if df_tables.empty:
            return df_tables  # nothing to clean

        # 1) Rename a fixed set of columns to lowercase
        cols_to_lower_case = [
            "STATISTICS_NAME", "TITLE", "CYCLE", "SURVEY_DATE",
            "OPEN_DATE", "SMALL_AREA", "COLLECT_AREA", "OVERALL_TOTAL_NUMBER",
            "UPDATED_DATE", "DESCRIPTION",
        ]
        renamer = {orig: orig.lower() for orig in cols_to_lower_case}
        renamer["@id"] = "statsDataId"
        df_tables = df_tables.rename(columns=renamer)

        # 2) Flatten some JSON‐typed columns into separate “_code” and “_name”
        json_columns = ["STAT_NAME", "GOV_ORG", "MAIN_CATEGORY", "SUB_CATEGORY"]
        for col in json_columns:
            df_tables[col.lower() + "_code"] = df_tables[col].apply(
                lambda x: x.get("@code") if isinstance(x, dict) else None
            )
            df_tables[col.lower() + "_name"] = df_tables[col].apply(
                lambda x: x.get("$") if isinstance(x, dict) else None
            )

        # 3) Extract nested fields from STATISTICS_NAME_SPEC and TITLE_SPEC
        df_tables["statistics_name_spec_category"] = df_tables["STATISTICS_NAME_SPEC"].apply(
            lambda x: x.get("TABULATION_CATEGORY") if isinstance(x, dict) else None
        )
        df_tables["statistics_name_spec_sub_category1"] = df_tables["STATISTICS_NAME_SPEC"].apply(
            lambda x: x.get("TABULATION_SUB_CATEGORY1") if isinstance(x, dict) else None
        )

        df_tables["title_spec_name"] = df_tables["TITLE_SPEC"].apply(
            lambda x: x.get("TABLE_NAME") if isinstance(x, dict) else None
        )
        df_tables["title_spec_explanation"] = df_tables["TITLE_SPEC"].apply(
            lambda x: x.get("TABLE_EXPLANATION") if isinstance(x, dict) else None
        )

        # 4) Drop the original JSON columns (we already flattened them)
        drop_cols = json_columns + ["STATISTICS_NAME_SPEC", "TITLE_SPEC"]
        return df_tables.drop(columns=drop_cols, errors="ignore")

    def save(self, data: pd.DataFrame, path: str):
        """
        Save the final cleaned DataFrame to CSV at the given path.
        """
        print(f"\nWriting output to: {path}")
        data.to_csv(path, index=False)
        print("→ Done.")

    def run(self):
        # 1) Hard‐coded CSV of statsField codes (same as your previous script)
        path_list = os.path.join("data", "official", "statsfield.csv")
        df_statsfields = pd.read_csv(path_list, dtype="object", header=0)
        list_statsfields = sorted(df_statsfields["大分類コード"].unique())

        # 2) Fetch raw tables for years 2024 & 2023
        raw_df = self.fetch(stats_data_ids=list_statsfields, years=["2024", "2023"], lang="J")

        # 3) Clean them
        cleaned_df = self.clean(raw_df)

        # 4) Write final CSV (same path as before)
        output_path = os.path.join("data", "collected", "retrieved_tables_via_statsfield_test.csv")
        self.save(cleaned_df, output_path)
