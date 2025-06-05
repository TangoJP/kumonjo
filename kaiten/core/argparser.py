import argparse
from abc import ABC, abstractmethod

class BaseArgParser(ABC):

    @staticmethod
    def parse_args():
        parser = argparse.ArgumentParser(description="Retriever CLI")
        parser.add_argument("--api_key", required=True, help="API key for the service")
        parser.add_argument("--year", required=False, help="survey year to be input")
        return parser.parse_args()

class EStatsArgParser(BaseArgParser):
    
    @staticmethod
    def parse_args():
        parser = argparse.ArgumentParser(description="Retriever CLI")
        parser.add_argument("--api_key", required=True, help="API key for the service")
        parser.add_argument("--lang", default="J", required=False, help="language")
        parser.add_argument("--year", default="2024", required=False, help="survey year to be input")
        parser.add_argument("--statsField", default="00", required=False, help="statsField")
        parser.add_argument("--statsDataId", default="0000000000", required=False, help="statsDataId")
        return parser.parse_args()