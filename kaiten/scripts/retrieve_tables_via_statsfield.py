import pandas as pd
import requests
import json
import os
from datetime import datetime
from dotenv import load_dotenv
# from pathlib import Path


load_dotenv()

def get_tables_single_year_statsDataId(params: dict) -> dict:
    
    url = f"https://api.e-stat.go.jp/rest/3.0/app/json/getStatsList"

    response = requests.get(url, params=params)
    print(f"Response {response.status_code}")
    
    if response.status_code == 200:
        try:
            return response.json()
        except json.JSONDecodeError:
            print("Failed to decode JSON.")
            return {}
    else:
        print(f"Error {response.status_code}: {response.text}")
        return {}

def get_tables_multi_year_statsDataId(appId: str, stats_data_ids: list, years: list, lang: str = 'J') -> dict:

    outputs = []
    for code in stats_data_ids:
        for year in years:
            print(f"\Retrieving tables for statsDataId={code} for year={year}")

            params = {
                'appId': appId,
                'statsField': code,
                'surveyYears': year,
                'lang': lang
            }

            response = get_tables_single_year_statsDataId(params)
            
            if response is not None:
                if response['GET_STATS_LIST']['DATALIST_INF']['NUMBER'] == 0:
                    print("Valid response with no data available")
                    continue

                df = pd.DataFrame(response['GET_STATS_LIST']['DATALIST_INF']['TABLE_INF'])
                df['retrieved_at'] = datetime.now()
                df['statsField'] = code
                df['surveyYears'] = params['surveyYears']
                outputs.append(df)

    df_tables = pd.concat(outputs, axis=0).reset_index()
    
    return df_tables

def clean_statsDataId_table(df_tables):
    
    # rename some columns first
    cols_to_lower_case = [
        'STATISTICS_NAME', 
        'TITLE', 
        'CYCLE', 
        'SURVEY_DATE',
        'OPEN_DATE', 
        'SMALL_AREA', 
        'COLLECT_AREA', 
        'OVERALL_TOTAL_NUMBER',
        'UPDATED_DATE', 
        'DESCRIPTION',
    ]
    
    renamer = {k: k.lower() for k in cols_to_lower_case}
    renamer['@id'] = 'statsDataId'

    df_tables = df_tables.rename(columns=renamer)

    # process json columns
    cols_json = [
        'STAT_NAME',
        'GOV_ORG',
        'MAIN_CATEGORY',
        'SUB_CATEGORY',
    ]

    for c in cols_json:
        df_tables[c.lower() + '_code'] = df_tables.loc[:, c].apply(lambda x: x.get('@code'))
        df_tables[c.lower() + '_name'] = df_tables.loc[:, c].apply(lambda x: x.get('$'))

    # process other json columns
    df_tables['statistics_name_spec_category'] = df_tables.loc[:, 'STATISTICS_NAME_SPEC'].apply(lambda x: x.get('TABULATION_CATEGORY'))
    df_tables['statistics_name_spec_sub_category1'] = df_tables.loc[:, 'STATISTICS_NAME_SPEC'].apply(lambda x: x.get('TABULATION_SUB_CATEGORY1'))
    
    df_tables['title_spec_name'] = df_tables.loc[:, 'TITLE_SPEC'].apply(lambda x: x.get('TABLE_NAME'))
    df_tables['title_spec_explanation'] = df_tables.loc[:, 'TITLE_SPEC'].apply(lambda x: x.get('TABLE_EXPLANATION'))
    
    df_tables = df_tables.drop(cols_json + ['STATISTICS_NAME_SPEC', 'TITLE_SPEC'], axis=1)

    return df_tables


if __name__ == '__main__':

    path_list = 'data/official/statsfield.csv'
    df_statsfields = pd.read_csv(path_list, dtype='object', header=0)
    list_statsfields = sorted(list(df_statsfields['大分類コード'].unique()))

    load_dotenv('.env')

    df_raw = get_tables_multi_year_statsDataId(
        appId=os.getenv('APP_ID'),
        stats_data_ids=list_statsfields,
        years=['2024', '2023'],
        lang='J'
    )

    df_clean = clean_statsDataId_table(df_raw)

    path_output = 'data/collected/retrieved_tables_via_statsfield.csv'
    print(f"Writing table to {path_output}")
    df_clean.to_csv(path_output, index=False)