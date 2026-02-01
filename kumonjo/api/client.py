"""Thin e-Stat API client: getStatsList, getStatsData."""

import logging
from typing import Any

import requests

BASE_URL_LIST = "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsList"
BASE_URL_DATA = "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData"

logger = logging.getLogger(__name__)


class EstatAPIError(Exception):
    """e-Stat API returned STATUS != 0 (e.g. auth failure). Do not save or use the response."""

    def __init__(self, status: int, message: str, endpoint: str = ""):
        self.status = status
        self.message = message
        self.endpoint = endpoint
        super().__init__(f"e-Stat API error (STATUS={status}): {message}")


def _check_stats_data_result(data: dict[str, Any]) -> None:
    """Raise EstatAPIError if GET_STATS_DATA.RESULT indicates an error. Do not save response."""
    result = data.get("GET_STATS_DATA", {}).get("RESULT", {})
    status = result.get("STATUS", 0)
    if status != 0:
        msg = result.get("ERROR_MSG", "Unknown error")
        raise EstatAPIError(status, msg, "getStatsData")


def _check_stats_list_result(data: dict[str, Any]) -> None:
    """Raise EstatAPIError if GET_STATS_LIST.RESULT indicates an error. Do not save response.
    STATUS=0: success with data; STATUS=1: success but no data (正常に終了しましたが、該当データはありませんでした).
    Only STATUS >= 100 (e.g. auth failure) is treated as error."""
    result = data.get("GET_STATS_LIST", {}).get("RESULT", {})
    if not result:
        return
    status = result.get("STATUS", 0)
    if status >= 100:  # real errors (e.g. 100 = auth failure); 0 and 1 are success / no-data
        msg = result.get("ERROR_MSG", "Unknown error")
        raise EstatAPIError(status, msg, "getStatsList")


def get_stats_list(
    app_id: str,
    stats_field: str,
    survey_years: str,
    lang: str = "J",
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """
    Call getStatsList: list tables (statsDataIds) for a statsField and year.
    Returns raw JSON response; use processing.clean_list to build a catalog DataFrame.
    Raises EstatAPIError if the API returns STATUS != 0 (do not save that response).
    """
    params = {
        "appId": app_id,
        "statsField": stats_field,
        "surveyYears": survey_years,
        "lang": lang,
    }
    sess = session or requests.Session()
    resp = sess.get(BASE_URL_LIST, params=params)
    logger.info("GET %s -> %s", resp.url.replace(app_id, "APPID_MASKED"), resp.status_code)
    resp.raise_for_status()
    data = resp.json()
    _check_stats_list_result(data)
    return data


def get_stats_data(
    app_id: str,
    stats_data_id: str,
    survey_years: str,
    lang: str = "J",
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """
    Call getStatsData: fetch table data for a statsDataId and year.
    Returns raw JSON; use processing.parse_response to build a DataFrame.
    Raises EstatAPIError if the API returns STATUS != 0 (do not save that response).
    """
    params = {
        "appId": app_id,
        "statsDataId": stats_data_id,
        "surveyYears": survey_years,
        "lang": lang,
    }
    sess = session or requests.Session()
    resp = sess.get(BASE_URL_DATA, params=params)
    logger.info("GET %s -> %s", resp.url.replace(app_id, "APPID_MASKED"), resp.status_code)
    resp.raise_for_status()
    data = resp.json()
    _check_stats_data_result(data)
    return data
