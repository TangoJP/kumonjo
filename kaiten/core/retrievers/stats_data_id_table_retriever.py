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


class StatsDataIdTableRetriever(BaseRetriever):
    def __init__(
            self,
            api_key: str,
            statsDataId: str,
            year: str,
            lang: str = "J",
            output_dir="data/raw"
        ):
        super().__init__(api_key)
        self.params = {
            "appId": self.api_key,
            "statsDataId": statsDataId,
            "surveyYears": year,
            "lang": lang,
        }
        
        self.output_dir = os.path.join(output_dir, lang, "statsDataId")
        os.makedirs(self.output_dir, exist_ok=True)

        self.result = None
        self.run_date = date.today().strftime('%Y%m%d')

    def set_base_url(self) -> str:
        return "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData"

    def fetch(self) -> dict:
        response_raw = self.session.get(self.base_url, params=self.params)
        url = response_raw.url.replace(self.params["appId"], 'APPID_MASKED')
        request_id = hashlib.sha256(url.encode("utf-8")).hexdigest()

        logging.info(f"GET {url} -> {response_raw.status_code}")

        output = {
            "request_id": request_id, 
            "requested_url": url,
            "status_code": response_raw.status_code,
            "timestamp": datetime.now().isoformat(),
            "retrieval_date": self.run_date
        }

        try:
            response_raw.raise_for_status()

            if response_raw.status_code == 200:
                try:
                    response = response_raw.json()
                    output["response"] = response
                    logging.info(f"Successfully decoded JSON")
                except json.JSONDecodeError as e:
                    logging.info(f"Failed to decode JSON: {e}")

            else:
                logging.info(f"Error {response_raw.status_code}: {response_raw.text}")

        except requests.exceptions.HTTPError as e:
            logging.info(f"HTTP Error: {e}")

        return output

    def run(self):
        output_path = os.path.join(
            self.output_dir, 
            f"{self.params['surveyYears']}_statsDataId_{self.params['statsDataId']}.json"
        )
        
        self.result = self.fetch()
        if self.result:
            self.save(self.result, output_path)
            logging.info(f"file saved to {output_path}")
        elif self.result["status_code"] == "200":
            logging.info("> Valid response, but no data available.")
        else:
            logging.info("No results found")