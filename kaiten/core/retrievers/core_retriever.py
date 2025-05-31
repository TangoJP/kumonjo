import argparse
import logging
import requests
from abc import ABC, abstractmethod
from typing import Any, Dict

class BaseRetriever(ABC):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = self.set_base_url()  # subclass must provide this
        self.session = requests.Session()
        logging.basicConfig(level=logging.INFO)

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