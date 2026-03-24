from datetime import datetime
import time

from src.common.logging_utils import get_app_logger, get_error_logger
from src.config.settings import settings
from src.data_access.raw_data_repository import RawDataRepository
from src.data_access.standardized_data_repository import StandardizedDataRepository
from src.datasources.tushare_provider import TushareProvider


def _yyyymmdd_to_iso(date_str: str) -> str:
    s = str(date_str)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def _iso_to_yyyymmdd(date_str: str) -> str:
    return str(date_str).replace("-", "")


class DailyFundamentalsIngestor:
    def __init__(self):
        self.provider = TushareProvider()
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

    def backfill(
        self,
        start_date: str,
        end_date: str,
        sleep_seconds: float = 0.5,
        max_trade_days: int | None = None,
    ) -> dict:
        self.app_logger.info(
            f"[DailyFundamentalsIngestor] 开始回填 daily_basic, start_date={start_date}, "
            f"end_date={end_date}, max_trade_days={max_trade_days}"
        )

        trade_dates = self._get_open_trade_dates(start_date, end_date)

        if not trade_dates:
            self.app_logger.warning(
                "[DailyFundamentalsIngestor] 未找到可用交易日，请先确认 std_calendar 已构建"
            )
            return {
                "total_rows": 0,
                "success_slices": [],
                "empty_slices": [],
                "failed_slices": [],
                "processed_trade_dates": [],
                "total_trade_dates": 0,
                "planned_trade_dates": [],
            }

        if max_trade_days is not None and max_trade_days > 0:
            trade_dates = trade_dates[:max_trade_days]

        total_rows = 0
        success_slices: list[dict] = []
        empty_slices: list[dict] = []
        failed_slices: list[dict] = []
        processed_trade_dates: list[str] = []

        expected_columns = [
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

        for trade_date_iso in trade_dates:
            trade_date = _iso_to_yyyymmdd(trade_date_iso)
            processed_trade_dates.append(trade_date)

            self.app_logger.info(
                f"[DailyFundamentalsIngestor] 拉取 daily_basic, trade_date={trade_date}"
            )

            try:
                df = self.provider.get_daily_basic(trade_date=trade_date)

                if df.empty:
                    self.app_logger.warning(
                        f"[DailyFundamentalsIngestor] daily_basic 无数据, trade_date={trade_date}"
                    )
                    empty_slices.append(
                        {
                            "trade_date": trade_date,
                            "rows": 0,
                        }
                    )
                    time.sleep(sleep_seconds)
                    continue

                for col in expected_columns:
                    if col not in df.columns:
                        df[col] = None

                df = df[expected_columns].copy()
                df["ingest_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                self.raw_repo.upsert_dataframe(
                    table_name="ods_daily_basic",
                    df=df,
                    unique_keys=["ts_code", "trade_date"],
                )

                row_count = len(df)
                total_rows += row_count

                success_slices.append(
                    {
                        "trade_date": trade_date,
                        "rows": row_count,
                    }
                )

                self.app_logger.info(
                    f"[DailyFundamentalsIngestor] daily_basic 回填完成, trade_date={trade_date}, 写入/更新 {row_count} 行"
                )

            except Exception as e:
                failed_info = {
                    "trade_date": trade_date,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                }
                failed_slices.append(failed_info)

                self.error_logger.exception(
                    f"[DailyFundamentalsIngestor] daily_basic 分片失败, trade_date={trade_date}, "
                    f"error={type(e).__name__}: {e}"
                )

            time.sleep(sleep_seconds)

        self.app_logger.info(
            f"[DailyFundamentalsIngestor] daily_basic 回填结束, total_rows={total_rows}, "
            f"success_slices={len(success_slices)}, empty_slices={len(empty_slices)}, "
            f"failed_slices={len(failed_slices)}, total_trade_dates={len(trade_dates)}"
        )

        return {
            "total_rows": total_rows,
            "success_slices": success_slices,
            "empty_slices": empty_slices,
            "failed_slices": failed_slices,
            "processed_trade_dates": processed_trade_dates,
            "total_trade_dates": len(trade_dates),
            "planned_trade_dates": trade_dates,
        }