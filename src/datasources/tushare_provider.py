from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

import pandas as pd

from src.common.logging_utils import get_app_logger, get_error_logger
from src.config.settings import settings


TUSHARE_PERMISSION_ERROR_CODE = 2002


class TushareAPIError(RuntimeError):
    """Tushare API 层错误。"""

    def __init__(
        self,
        api_name: str,
        code: Any,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        self.api_name = api_name
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(
            f"Tushare API 调用失败: api_name={api_name}, code={code}, msg={message}"
        )


class TusharePermissionError(TushareAPIError):
    """
    Tushare 接口权限错误。

    官方 HTTP 协议文档说明 code=2002 表示权限问题。
    该类错误不会通过重试恢复，应该由上层停止当前接口的重复回填，
    同时允许系统的其他可用接口继续运行。
    """

    def __init__(
        self,
        api_name: str,
        code: Any,
        message: str,
        *,
        detected_at: str | None = None,
        cached: bool = False,
    ) -> None:
        self.detected_at = detected_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cached = cached
        super().__init__(
            api_name=api_name,
            code=code,
            message=message,
            retryable=False,
        )


class TushareProvider:
    def __init__(self):
        if not settings.TUSHARE_TOKEN:
            raise ValueError("TUSHARE_TOKEN 未配置，请先检查 D:\\quant_system\\.env")

        self.token = settings.TUSHARE_TOKEN
        self.base_url = "http://api.tushare.pro"
        self.app_logger = get_app_logger()
        self.error_logger = get_error_logger()

        # 当前进程内的权限熔断缓存。
        # 某个接口一旦明确返回权限错误，就不再继续发送同一接口请求，
        # 避免长历史回填把几百个交易日全部打成失败。
        self._permission_failures: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _is_permission_error(code: Any, msg: str) -> bool:
        if code == TUSHARE_PERMISSION_ERROR_CODE:
            return True

        normalized = (msg or "").strip().lower()
        permission_markers = (
            "没有权限",
            "无权限",
            "权限不足",
            "接口权限",
            "permission denied",
            "no permission",
        )
        return any(marker in normalized for marker in permission_markers)

    @staticmethod
    def _is_retryable_api_error(msg: str) -> bool:
        """仅对明显可能瞬时恢复的 API 层错误进行重试。"""
        normalized = (msg or "").strip().lower()
        retryable_markers = (
            "系统内部错误",
            "服务异常",
            "稍后再试",
            "繁忙",
            "频次",
            "每分钟",
            "timeout",
            "temporarily",
            "busy",
        )
        return any(marker in normalized for marker in retryable_markers)

    def get_permission_failure(self, api_name: str) -> dict[str, Any] | None:
        failure = self._permission_failures.get(api_name)
        return dict(failure) if failure else None

    def _raise_cached_permission_error(self, api_name: str) -> None:
        cached = self._permission_failures.get(api_name)
        if not cached:
            return

        raise TusharePermissionError(
            api_name=api_name,
            code=cached.get("code"),
            message=cached.get("msg", "权限不可用"),
            detected_at=cached.get("detected_at"),
            cached=True,
        )

    def _post_api(
        self,
        api_name: str,
        params: dict[str, Any] | None = None,
        fields: str = "",
        max_retries: int = 3,
        retry_sleep_seconds: int = 3,
    ) -> pd.DataFrame:
        self._raise_cached_permission_error(api_name)

        payload = {
            "api_name": api_name,
            "token": self.token,
            "params": params or {},
            "fields": fields,
        }

        self.app_logger.info(
            f"[TushareProvider] HTTP调用 {api_name}, params={payload['params']}, fields={fields}"
        )

        last_error: Exception | None = None

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

                if self._is_permission_error(code, msg):
                    detected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self._permission_failures[api_name] = {
                        "api_name": api_name,
                        "code": code,
                        "msg": msg,
                        "detected_at": detected_at,
                    }
                    self.error_logger.error(
                        f"[TushareProvider] 接口权限不可用，停止重试: "
                        f"api_name={api_name}, code={code}, msg={msg}, detected_at={detected_at}"
                    )
                    raise TusharePermissionError(
                        api_name=api_name,
                        code=code,
                        message=msg,
                        detected_at=detected_at,
                    )

                if code != 0:
                    retryable = self._is_retryable_api_error(msg)
                    raise TushareAPIError(
                        api_name=api_name,
                        code=code,
                        message=msg,
                        retryable=retryable,
                    )

                if not fields_list:
                    self.app_logger.warning(
                        f"[TushareProvider] {api_name} 返回成功但 fields 为空"
                    )
                    return pd.DataFrame()

                return pd.DataFrame(items, columns=fields_list)

            except TusharePermissionError:
                # 权限到期/积分不足/未开权限不可能靠重试恢复。
                raise

            except TushareAPIError as e:
                last_error = e
                self.error_logger.error(
                    f"[TushareProvider] APIError: api_name={api_name}, "
                    f"attempt={attempt}/{max_retries}, code={e.code}, "
                    f"retryable={e.retryable}, msg={e.message}"
                )

                if not e.retryable or attempt >= max_retries:
                    raise

                time.sleep(retry_sleep_seconds * attempt)

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
                        f"[TushareProvider] HTTP调用最终失败: api_name={api_name}, "
                        f"error={type(e).__name__}: {e}"
                    )
                    raise

            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                last_error = e
                self.error_logger.error(
                    f"[TushareProvider] 可重试传输错误: api_name={api_name}, "
                    f"attempt={attempt}/{max_retries}, error={type(e).__name__}: {e}"
                )
                if attempt < max_retries:
                    time.sleep(retry_sleep_seconds * attempt)
                else:
                    raise

            except Exception as e:
                last_error = e
                self.error_logger.exception(
                    f"[TushareProvider] 非预期错误: api_name={api_name}, "
                    f"attempt={attempt}/{max_retries}, error={type(e).__name__}: {e}"
                )
                raise

        if last_error:
            raise last_error

        return pd.DataFrame()

    def probe_api_permission(
        self,
        api_name: str,
        params: dict[str, Any] | None = None,
        fields: str = "",
    ) -> dict[str, Any]:
        """
        对一个接口做单次轻量探测。

        该方法不会泄露 token，返回结果适合直接持久化到权限审计 JSON。
        """
        checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            df = self._post_api(
                api_name=api_name,
                params=params,
                fields=fields,
                max_retries=1,
                retry_sleep_seconds=1,
            )
            return {
                "api_name": api_name,
                "status": "AVAILABLE",
                "checked_at": checked_at,
                "code": 0,
                "message": "",
                "rows": int(len(df)),
            }

        except TusharePermissionError as e:
            return {
                "api_name": api_name,
                "status": "PERMISSION_DENIED",
                "checked_at": checked_at,
                "code": e.code,
                "message": e.message,
                "rows": 0,
            }

        except TushareAPIError as e:
            return {
                "api_name": api_name,
                "status": "API_ERROR",
                "checked_at": checked_at,
                "code": e.code,
                "message": e.message,
                "rows": 0,
            }

        except Exception as e:
            return {
                "api_name": api_name,
                "status": "NETWORK_OR_UNKNOWN_ERROR",
                "checked_at": checked_at,
                "code": None,
                "message": f"{type(e).__name__}: {e}",
                "rows": 0,
            }

    def audit_core_permissions(
        self,
        probe_trade_date: str = "20240102",
        probe_ts_code: str = "000001.SZ",
    ) -> list[dict[str, Any]]:
        """探测当前数据准备层实际依赖的核心 Tushare 接口。"""
        probes = [
            {
                "api_name": "trade_cal",
                "params": {
                    "exchange": "",
                    "start_date": probe_trade_date,
                    "end_date": probe_trade_date,
                },
                "fields": "exchange,cal_date,is_open,pretrade_date",
            },
            {
                "api_name": "stock_basic",
                "params": {
                    "ts_code": probe_ts_code,
                    "list_status": "L",
                },
                "fields": "ts_code,name,list_date",
            },
            {
                "api_name": "daily",
                "params": {
                    "ts_code": probe_ts_code,
                    "start_date": probe_trade_date,
                    "end_date": probe_trade_date,
                },
                "fields": "ts_code,trade_date,close",
            },
            {
                "api_name": "daily_basic",
                "params": {
                    "ts_code": probe_ts_code,
                    "start_date": probe_trade_date,
                    "end_date": probe_trade_date,
                },
                "fields": "ts_code,trade_date,close,total_mv,circ_mv",
            },
            {
                "api_name": "adj_factor",
                "params": {
                    "ts_code": probe_ts_code,
                    "start_date": probe_trade_date,
                    "end_date": probe_trade_date,
                },
                "fields": "ts_code,trade_date,adj_factor",
            },
        ]

        return [
            self.probe_api_permission(
                api_name=probe["api_name"],
                params=probe["params"],
                fields=probe["fields"],
            )
            for probe in probes
        ]

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