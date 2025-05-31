import argparse
import logging
import requests
from abc import ABC, abstractmethod
from typing import Any, Dict

class BaseRetriever(ABC):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = self.get_base_url()  # subclass must provide this
        self.session = requests.Session()
        logging.basicConfig(level=logging.INFO)

    @abstractmethod
    def get_base_url(self) -> str:
        pass

    def get(self, endpoint: str, params: Dict[str, Any]) -> Dict:
        params["appId"] = self.api_key
        url = f"{self.base_url}/{endpoint}"
        response = self.session.get(url, params=params)
        logging.info(f"GET {response.url} -> {response.status_code}")
        response.raise_for_status()
        return response.json()

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
        return parser.parse_args()

    @abstractmethod
    def run(self):
        pass