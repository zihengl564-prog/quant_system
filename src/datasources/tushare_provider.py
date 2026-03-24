import json
import time
import urllib.error
import urllib.request
from typing import Any

import pandas as pd

from src.common.logging_utils import get_app_logger, get_error_logger
from src.config.settings import settings


class TushareProvider:
    def __init__(self):
        if not settings.TUSHARE_TOKEN:
            raise ValueError("TUSHARE_TOKEN 未配置，请先检查 D:\\quant_system\\.env")

        self.token = settings.TUSHARE_TOKEN
        self.base_url = "http://api.tushare.pro"
        self.app_logger = get_app_logger()
        self.error_logger = get_error_logger()

    def _post_api(
        self,
        api_name: str,
        params: dict[str, Any] | None = None,
        fields: str = "",
        max_retries: int = 3,
        retry_sleep_seconds: int = 3,
    ) -> pd.DataFrame:
        payload = {
            "api_name": api_name,
            "token": self.token,
            "params": params or {},
            "fields": fields,
        }

        self.app_logger.info(
            f"[TushareProvider] HTTP调用 {api_name}, params={payload['params']}, fields={fields}"
        )

        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                req = urllib.request.Request(
                    self.base_url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )

                with urllib.request.urlopen(req, timeout=30) as resp:
                    text = resp.read().decode("utf-8")

                result = json.loads(text)

                code = result.get("code")
                msg = result.get("msg", "")
                data = result.get("data") or {}
                fields_list = data.get("fields") or []
                items = data.get("items") or []

                self.app_logger.info(
                    f"[TushareProvider] {api_name} 返回 code={code}, "
                    f"fields_count={len(fields_list)}, rows={len(items)}, msg={msg}"
                )

                if code != 0:
                    raise RuntimeError(
                        f"Tushare API 调用失败: api_name={api_name}, code={code}, msg={msg}"
                    )

                if not fields_list:
                    self.app_logger.warning(
                        f"[TushareProvider] {api_name} 返回成功但 fields 为空"
                    )
                    return pd.DataFrame()

                return pd.DataFrame(items, columns=fields_list)

            except urllib.error.HTTPError as e:
                last_error = e
                self.error_logger.error(
                    f"[TushareProvider] HTTPError: api_name={api_name}, attempt={attempt}/{max_retries}, "
                    f"status={e.code}, reason={e.reason}"
                )
                if attempt < max_retries:
                    time.sleep(retry_sleep_seconds * attempt)
                else:
                    self.error_logger.exception(
                        f"[TushareProvider] HTTP调用最终失败: api_name={api_name}, error={type(e).__name__}: {e}"
                    )
                    raise

            except Exception as e:
                last_error = e
                self.error_logger.exception(
                    f"[TushareProvider] HTTP调用失败: api_name={api_name}, attempt={attempt}/{max_retries}, "
                    f"error={type(e).__name__}: {e}"
                )
                if attempt < max_retries:
                    time.sleep(retry_sleep_seconds * attempt)
                else:
                    raise

        if last_error:
            raise last_error

        return pd.DataFrame()

    def get_trade_calendar(
        self,
        exchange: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        params = {
            "exchange": "" if exchange is None else exchange,
            "start_date": start_date or settings.DEFAULT_START_DATE,
            "end_date": end_date or settings.DEFAULT_END_DATE,
        }
        fields = "exchange,cal_date,is_open,pretrade_date"
        return self._post_api("trade_cal", params=params, fields=fields)

    def get_stock_basic(
        self,
        exchange: str = "",
        list_status: str = "L",
    ) -> pd.DataFrame:
        params = {
            "exchange": exchange,
            "list_status": list_status,
        }
        fields = (
            "ts_code,symbol,name,area,industry,market,list_date,"
            "delist_date,is_hs,act_name,act_ent_type"
        )
        df = self._post_api("stock_basic", params=params, fields=fields)
        if not df.empty:
            df["list_status"] = list_status
        return df

    def get_daily(
        self,
        ts_code: str | None = None,
        trade_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        params: dict[str, Any] = {}
        if ts_code:
            params["ts_code"] = ts_code
        if trade_date:
            params["trade_date"] = trade_date
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        fields = (
            "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"
        )
        return self._post_api("daily", params=params, fields=fields)

    def get_daily_basic(
        self,
        ts_code: str | None = None,
        trade_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        params: dict[str, Any] = {}
        if ts_code:
            params["ts_code"] = ts_code
        if trade_date:
            params["trade_date"] = trade_date
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        fields = (
            "ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,"
            "pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,total_share,float_share,"
            "free_share,total_mv,circ_mv"
        )
        return self._post_api("daily_basic", params=params, fields=fields)

    def get_adj_factor(
        self,
        ts_code: str | None = None,
        trade_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        params: dict[str, Any] = {}
        if ts_code:
            params["ts_code"] = ts_code
        if trade_date:
            params["trade_date"] = trade_date
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        fields = "ts_code,trade_date,adj_factor"
        return self._post_api("adj_factor", params=params, fields=fields)