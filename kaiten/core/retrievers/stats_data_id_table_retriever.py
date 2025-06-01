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
        self.output_dir = output_dir + f"/{lang}/{year}/statsDataId"
        self.result = None

    @abstractmethod
    def set_base_url(self) -> str:
        pass

    @abstractmethod
    def fetch(self, *args, **kwargs):
        pass

    @abstractmethod
    def save(self, data: Any, path: str):
        pass

    @staticmethod
    def parse_args():
        parser = argparse.ArgumentParser(description="Retriever CLI")
        parser.add_argument("--api_key", required=True, help="API key for the service")
        parser.add_argument("--year", required=False, help="survey year to be input")
        return parser.parse_args()

    @abstractmethod
    def run(self):
        pass