from datetime import datetime
import time

import pandas as pd

from src.common.logging_utils import get_app_logger, get_error_logger
from src.config.settings import settings
from src.data_access.raw_data_repository import RawDataRepository
from src.data_access.standardized_data_repository import StandardizedDataRepository


def _yyyymmdd_to_iso(date_str: str) -> str:
    s = str(date_str)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def _iso_to_yyyymmdd(date_str: str) -> str:
    return str(date_str).replace("-", "")


class DailyBarBuilder:
    """
    当前阶段的 std_equity_daily 构建原则：
    1. 以 ods_daily 为基表
    2. left join ods_daily_basic / ods_adj_factor
    3. 再补 std_security_master 的 industry / market
    4. 允许 daily_basic / adj_factor 某些日期为空，后续可反复重跑补齐
    5. open_adj/high_adj/low_adj/close_adj 暂使用 价格 * adj_factor 的桥梁口径
       后续若需要严格前复权/后复权口径，可在特征层或更高标准化层再统一处理
    """

    def __init__(self):
        self.raw_repo = RawDataRepository(settings.RAW_DB_PATH)
        self.std_repo = StandardizedDataRepository(settings.STD_DB_PATH)
        self.app_logger = get_app_logger()
        self.error_logger = get_error_logger()

    def _get_open_trade_dates(
        self,
        start_date: str,
        end_date: str,
    ) -> list[str]:
        start_iso = _yyyymmdd_to_iso(start_date)
        end_iso = _yyyymmdd_to_iso(end_date)

        rows = self.std_repo.fetch_all(
            """
            SELECT trade_date
            FROM std_calendar
            WHERE is_open = 1
              AND trade_date >= ?
              AND trade_date <= ?
            ORDER BY trade_date;
            """,
            (start_iso, end_iso),
        )

        return [row["trade_date"] for row in rows]

    def _fetch_raw_df(
        self,
        table_name: str,
        trade_date: str,
        columns: list[str],
    ) -> pd.DataFrame:
        sql = f"""
        SELECT {", ".join(columns)}
        FROM {table_name}
        WHERE trade_date = ?;
        """
        rows = self.raw_repo.fetch_all(sql, (trade_date,))
        if not rows:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame([dict(row) for row in rows])

    def _fetch_security_master(self) -> pd.DataFrame:
        rows = self.std_repo.fetch_all(
            """
            SELECT ts_code, industry, market
            FROM std_security_master;
            """
        )
        if not rows:
            return pd.DataFrame(columns=["ts_code", "industry", "market"])
        return pd.DataFrame([dict(row) for row in rows])

    def build(
        self,
        start_date: str,
        end_date: str,
        max_trade_days: int | None = None,
        sleep_seconds: float = 0.1,
    ) -> dict:
        self.app_logger.info(
            f"[DailyBarBuilder] 开始构建 std_equity_daily, start_date={start_date}, "
            f"end_date={end_date}, max_trade_days={max_trade_days}"
        )

        trade_dates_iso = self._get_open_trade_dates(start_date, end_date)

        if not trade_dates_iso:
            self.app_logger.warning("[DailyBarBuilder] 未找到可用交易日")
            return {
                "total_rows": 0,
                "success_slices": [],
                "empty_slices": [],
                "failed_slices": [],
                "processed_trade_dates": [],
                "total_trade_dates": 0,
            }

        if max_trade_days is not None and max_trade_days > 0:
            trade_dates_iso = trade_dates_iso[:max_trade_days]

        security_df = self._fetch_security_master()

        total_rows = 0
        success_slices: list[dict] = []
        empty_slices: list[dict] = []
        failed_slices: list[dict] = []
        processed_trade_dates: list[str] = []

        daily_cols = [
            "ts_code",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "change",
            "pct_chg",
            "vol",
            "amount",
        ]

        daily_basic_cols = [
            "ts_code",
            "trade_date",
            "close",
            "turnover_rate",
            "turnover_rate_f",
            "volume_ratio",
            "pe",
            "pe_ttm",
            "pb",
            "ps",
            "ps_ttm",
            "dv_ratio",
            "dv_ttm",
            "total_share",
            "float_share",
            "free_share",
            "total_mv",
            "circ_mv",
        ]

        adj_cols = [
            "ts_code",
            "trade_date",
            "adj_factor",
        ]

        for trade_date_iso in trade_dates_iso:
            trade_date_raw = _iso_to_yyyymmdd(trade_date_iso)
            processed_trade_dates.append(trade_date_raw)

            self.app_logger.info(
                f"[DailyBarBuilder] 构建 std_equity_daily, trade_date={trade_date_raw}"
            )

            try:
                daily_df = self._fetch_raw_df("ods_daily", trade_date_raw, daily_cols)

                if daily_df.empty:
                    self.app_logger.warning(
                        f"[DailyBarBuilder] ods_daily 无数据, trade_date={trade_date_raw}"
                    )
                    empty_slices.append(
                        {
                            "trade_date": trade_date_raw,
                            "reason": "daily_missing",
                            "rows": 0,
                        }
                    )
                    time.sleep(sleep_seconds)
                    continue

                daily_basic_df = self._fetch_raw_df(
                    "ods_daily_basic",
                    trade_date_raw,
                    daily_basic_cols,
                )
                adj_df = self._fetch_raw_df(
                    "ods_adj_factor",
                    trade_date_raw,
                    adj_cols,
                )

                merged = daily_df.merge(
                    daily_basic_df,
                    on=["ts_code", "trade_date"],
                    how="left",
                    suffixes=("", "_db"),
                )

                merged = merged.merge(
                    adj_df,
                    on=["ts_code", "trade_date"],
                    how="left",
                )

                if not security_df.empty:
                    merged = merged.merge(
                        security_df,
                        on="ts_code",
                        how="left",
                    )
                else:
                    merged["industry"] = None
                    merged["market"] = None

                numeric_cols = [
                    "open",
                    "high",
                    "low",
                    "close",
                    "pre_close",
                    "vol",
                    "amount",
                    "adj_factor",
                    "turnover_rate",
                    "turnover_rate_f",
                    "volume_ratio",
                    "pe_ttm",
                    "pb",
                    "ps_ttm",
                    "total_mv",
                    "circ_mv",
                ]

                for col in numeric_cols:
                    if col in merged.columns:
                        merged[col] = pd.to_numeric(merged[col], errors="coerce")

                merged["trade_date"] = trade_date_iso

                merged["open_adj"] = merged["open"] * merged["adj_factor"]
                merged["high_adj"] = merged["high"] * merged["adj_factor"]
                merged["low_adj"] = merged["low"] * merged["adj_factor"]
                merged["close_adj"] = merged["close"] * merged["adj_factor"]

                merged["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                output_cols = [
                    "ts_code",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "pre_close",
                    "vol",
                    "amount",
                    "adj_factor",
                    "open_adj",
                    "high_adj",
                    "low_adj",
                    "close_adj",
                    "turnover_rate",
                    "turnover_rate_f",
                    "volume_ratio",
                    "pe_ttm",
                    "pb",
                    "ps_ttm",
                    "total_mv",
                    "circ_mv",
                    "industry",
                    "market",
                    "update_time",
                ]

                for col in output_cols:
                    if col not in merged.columns:
                        merged[col] = None

                output_df = merged[output_cols].copy()

                self.std_repo.upsert_dataframe(
                    table_name="std_equity_daily",
                    df=output_df,
                    unique_keys=["ts_code", "trade_date"],
                )

                row_count = len(output_df)
                total_rows += row_count

                success_slices.append(
                    {
                        "trade_date": trade_date_raw,
                        "rows": row_count,
                        "daily_basic_missing_rows": int(output_df["turnover_rate"].isna().sum()),
                        "adj_factor_missing_rows": int(output_df["adj_factor"].isna().sum()),
                    }
                )

                self.app_logger.info(
                    f"[DailyBarBuilder] std_equity_daily 构建完成, trade_date={trade_date_raw}, "
                    f"写入/更新 {row_count} 行"
                )

            except Exception as e:
                failed_info = {
                    "trade_date": trade_date_raw,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                }
                failed_slices.append(failed_info)

                self.error_logger.exception(
                    f"[DailyBarBuilder] std_equity_daily 构建失败, trade_date={trade_date_raw}, "
                    f"error={type(e).__name__}: {e}"
                )

            time.sleep(sleep_seconds)

        self.app_logger.info(
            f"[DailyBarBuilder] std_equity_daily 构建结束, total_rows={total_rows}, "
            f"success_slices={len(success_slices)}, empty_slices={len(empty_slices)}, "
            f"failed_slices={len(failed_slices)}, total_trade_dates={len(trade_dates_iso)}"
        )

        return {
            "total_rows": total_rows,
            "success_slices": success_slices,
            "empty_slices": empty_slices,
            "failed_slices": failed_slices,
            "processed_trade_dates": processed_trade_dates,
            "total_trade_dates": len(trade_dates_iso),
        }