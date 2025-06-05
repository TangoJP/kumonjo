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
            output_dir_raw="data/raw",
            output_dir_processed="data/processed"
        ):
        super().__init__(api_key)
        self.params = {
            "appId": self.api_key,
            "statsDataId": statsDataId,
            "surveyYears": year,
            "lang": lang,
        }
        
        self.output_dir_raw = os.path.join(output_dir_raw, lang, "statsDataId")
        self.output_dir_processed = os.path.join(output_dir_processed, lang, "statsDataId")
        os.makedirs(self.output_dir_raw, exist_ok=True)
        os.makedirs(self.output_dir_processed, exist_ok=True)

        self.result = None
        self.run_date = date.today().strftime('%Y%m%d')

    def set_base_url(self) -> str:
        return "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData"

    def fetch(self) -> dict:
        logging.info("Retrieving json response")

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

    def extract_annotations_single(self, class_obj: dict) -> list:

        #--- collect top level annotations ---#
        annotations_top_level = {}
        for k, v in class_obj.items():
            if k == 'CLASS':
                continue

            annotations_top_level[k] = v

        #--- process CLASS attribute ---#
        classes = class_obj['CLASS']
        
        # if classes is a dictionary
        if isinstance(classes, dict):
            for k, v in classes.items():
                annotations_top_level[k] = v
            annotations_top_level['@level'] = '0'
            annotations = [annotations_top_level]
            
        # elif classes is a list
        elif isinstance(classes, list):
            annotations = []
            for cls in classes:
                annot = annotations_top_level.copy()
                for k, v in cls.items():
                    annot[k] = v
                annotations.append(annot)
        
        # anything else raise TypeError
        else:
            TypeError("class_objs['CLASS'] is not dictionary nor list")

        return annotations

    def extract_annotations_whole(self, clean_column_names: bool=True) -> pd.DataFrame:
        response = self.result['response']
        class_objs = response['GET_STATS_DATA']['STATISTICAL_DATA']['CLASS_INF']['CLASS_OBJ']
        
        if not isinstance(class_objs, list):
            raise TypeError("response['GET_STATS_DATA']['STATISTICAL_DATA']['CLASS_INF']['CLASS_OBJ'] is not list")
        
        annotations = []
        for class_obj in class_objs:
            annotations += self.extract_annotations_single(class_obj)

        df_annotations = pd.DataFrame(annotations)
        
        if clean_column_names:
            renamer = {k: k.replace('@', '') for k in df_annotations.columns}
            df_annotations = df_annotations.rename(columns=renamer)
        
        return df_annotations

    def extract_values_raw(self) -> pd.DataFrame():
        response = self.result['response']
        data_info_value = response['GET_STATS_DATA']['STATISTICAL_DATA']['DATA_INF']['VALUE']
        df = pd.DataFrame(data_info_value)

        renamer = {k:k.replace('@', '') for k in df.columns}
        renamer['$'] = 'value'
        df = df.rename(columns=renamer)
        
        return df

    def extract_response(self) -> pd.DataFrame():
        logging.info("Extracting raw reponse into a DataFrame")
        
        if not self.result:
            logging.info("No raw response found. No DataFrame generated")
            return pd.DataFrame()
        
        df_annot = self.extract_annotations_whole(clean_column_names=True)
        df_values = self.extract_values_raw()

        for c in df_annot['id'].unique():
            df_annot_sub = df_annot[df_annot.id==c]

            if 'unit' in df_annot.columns:
                df_annot_sub = df_annot_sub.drop('unit', axis=1)
            cols_sub = [c for c in df_annot_sub.columns if c != 'id']
        
            df_values = df_values.merge(
                df_annot_sub,
                how='left',
                left_on=c,
                right_on='code'
            )
            df_values = df_values.rename(columns={
                k: f"{c}_{k}" for k in cols_sub
            })
            
            df_values = df_values.drop([c, 'id'], axis=1)

        return df_values

    @staticmethod
    def reorder_df_columns(df, offset=2) -> pd.DataFrame():
        cols = list(df.columns)
        new_order = cols[offset:] + cols[:offset]
        df = df[new_order]
        return df

    def run(self):
        logging.info(f"\n=============== statsDataId={self.params['statsDataId']} ===============")

        output_path_raw = os.path.join(
            self.output_dir_raw, 
            f"{self.params['surveyYears']}_statsDataId_{self.params['statsDataId']}.json"
        )

        # save json raw output
        self.result = self.fetch()
        if self.result:
            self.save(self.result, output_path_raw)
            logging.info(f"file saved to {output_path_raw}")
        elif self.result["status_code"] == "200":
            logging.info("> Valid response, but no data available.")
        else:
            logging.info("No results found")
        
        # save DataFrame
        df_values = self.extract_response()
        if not df_values.empty:
            output_path_df= os.path.join(
                self.output_dir_processed, 
                f"{self.params['surveyYears']}_statsDataId_{self.params['statsDataId']}.csv"
            )

            df_out = StatsDataIdTableRetriever.reorder_df_columns(df_values, offset=2)
            df_out.to_csv(output_path_df, index=False)
            logging.info(f"Saved combined DataFrame to: {output_path_df}")

        else:
            logging.info("No results found or DataFrame not generated")