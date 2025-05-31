import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import json
from datetime import datetime, date
import logging
import pandas as pd
import hashlib
import requests
from core_retriever import BaseRetriever

class SingleStatsFieldTableFetcher(BaseRetriever):
    def __init__(
            self, 
            api_key: str, 
            statsField: str, 
            year: str, 
            lang: str = "J",
            output_dir="data/raw"
        ):
        super().__init__(api_key)
        self.params = {
            "appId": self.api_key,
            "statsField": statsField,
            "surveyYears": year,
            "lang": lang,
        }
        self.output_dir = output_dir + f"/{lang}/{year}/statsField"
        self.result = None
    
    def set_base_url(self) -> str:
        # Set to e-Stat base endpoint (adjust as needed)
        return "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsList"

    def fetch(self) -> dict:
        response_raw = self.session.get(self.base_url, params=self.params)
        url = response_raw.url.replace(self.params["appId"], 'APPID_MASKED')
        request_id = hashlib.sha256(url.encode("utf-8")).hexdigest()

        logging.info(f"GET {url} -> {response_raw.status_code}")

        output = {
            "request_id": request_id, 
            "requested_url": url,
            "status_code": response_raw.status_code,
            "timestamp": datetime.now().isoformat()
        }

        try:
            response_raw.raise_for_status()

            response = response_raw.json()
            number_of_tables = (
                response
                .get("GET_STATS_LIST", {})
                .get("DATALIST_INF", {})
                .get("NUMBER", 0)
            )

            output["response"] = response
            output["number_of_tables"] = number_of_tables

        except requests.exceptions.HTTPError as e:
            print(f"HTTP Error: {e}")
            output["response"] = {}
            output["number_of_tables"] = 0

        return output

    def save(self, data: dict, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logging.info(f"Saved raw response to {path}")

    def run(self):
        os.makedirs(self.output_dir, exist_ok=True)
        filename = f"statsField_{self.params['statsField']}_{self.params['surveyYears']}_statsDataIds.json"
        output_path = os.path.join(self.output_dir, filename)
        
        self.result = self.fetch()
        if self.result and self.result["number_of_tables"] > 0:
            self.save(self.result, output_path)
            logging.info(f"Number of tables: {self.result['number_of_tables']}")
        elif self.result["status_code"] == "200":
            logging.info("> Valid response, but no data available.")
        else:
            logging.info("No results found")


class MultiStatsFieldTableFetcher:
    def __init__(
        self,
        api_key: str,
        year: str,
        statsFields: list,
        lang: str = "J",
        output_dir_raw: str = "data/raw",
        output_dir_processed: str = "data/processed"
    ):
        self.api_key = api_key
        self.year = year
        self.statsFields = statsFields
        self.lang = lang
        self.output_dir_raw = output_dir_raw
        self.output_dir_processed = output_dir_processed + f"/{lang}/{year}/listStatsFields"
        self.run_date = date.today().strftime('%Y%m%d')
        self.df_result = None

    def fetch_multiple(self):
        all_dfs = []
        for statsField in self.statsFields:
            print(f"\nRetrieving tables for statsField={statsField} for year={self.year}")
            
            single_fetcher = SingleStatsFieldTableFetcher(
                api_key=self.api_key,
                statsField=statsField,
                year=self.year,
                lang=self.lang,
                output_dir=self.output_dir_raw,
            )

            single_fetcher.run()
            if single_fetcher.result.get("number_of_tables", 0) == 0:
                continue

            response = single_fetcher.result.get("response", {})
            table_list = (
                response.get("GET_STATS_LIST", {})
                .get("DATALIST_INF", {})
                .get("TABLE_INF", [])
            )
            if table_list:
                df = pd.DataFrame(table_list)
                df["retrieved_at"] = datetime.now()
                df["statsField"] = statsField
                df["surveyYears"] = self.year
                all_dfs.append(df)

        if not all_dfs:
            df_result = pd.DataFrame()
        else:
            df_result = pd.concat(all_dfs, axis=0).reset_index(drop=True)
        
        self.df_result = df_result

        return 

    def save(self):
        if self.df_result.empty:
            print("No data to save.")
            return

        filename = f"list_statsDataIds_{self.run_date}.csv"
        save_dir = os.path.join(self.output_dir_processed)
        os.makedirs(save_dir, exist_ok=True)
        output_path = os.path.join(save_dir, filename)

        self.df_result.to_csv(output_path, index=False)
        print(f"Saved combined DataFrame to: {output_path}")

        return
    
    def run(self):
        self.fetch_multiple()
        self.save()