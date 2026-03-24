import argparse
from datetime import datetime, timedelta

from src.common.logging_utils import get_app_logger, get_error_logger, get_job_logger
from src.config.settings import settings
from src.data_access.job_log_repository import JobLogRepository
from src.pipelines.repair_daily_gaps_pipeline import RepairDailyGapsPipeline
from src.raw_ingest.trade_calendar_ingestor import TradeCalendarIngestor
from src.standardization.trading_calendar_builder import TradingCalendarBuilder


class DailyUpdatePipeline:
    """
    V1 日常更新策略：
    1. 刷新最近一段 trade_cal
    2. 重建 std_calendar
    3. 对最近窗口执行 repair_daily_gaps（补 ods_daily / ods_daily_basic / std_equity_daily）
    4. 不在 daily update 中刷新 stock_basic，避免把高波动/高失败率任务塞进每日链路
    """

    def __init__(self):
        self.trade_calendar_ingestor = TradeCalendarIngestor()
        self.trading_calendar_builder = TradingCalendarBuilder()
        self.repair_pipeline = RepairDailyGapsPipeline()

        self.job_repo = JobLogRepository(settings.STD_DB_PATH)
        self.app_logger = get_app_logger()
        self.job_logger = get_job_logger()
        self.error_logger = get_error_logger()

    @staticmethod
    def _shift_yyyymmdd(date_str: str, days: int) -> str:
        dt = datetime.strptime(date_str, "%Y%m%d")
        dt = dt + timedelta(days=days)
        return dt.strftime("%Y%m%d")

    def run(
        self,
        as_of_date: str | None = None,
        calendar_lookback_days: int = 60,
        calendar_forward_days: int = 30,
        repair_lookback_days: int = 20,
        max_daily_dates: int = 3,
        max_daily_basic_dates: int = 3,
        max_std_dates: int = 5,
    ) -> None:
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        as_of_date = as_of_date or datetime.now().strftime("%Y%m%d")
        calendar_start = self._shift_yyyymmdd(as_of_date, -calendar_lookback_days)
        calendar_end = self._shift_yyyymmdd(as_of_date, calendar_forward_days)
        repair_start = self._shift_yyyymmdd(as_of_date, -repair_lookback_days)
        repair_end = as_of_date

        self.job_logger.info(
            f"[DailyUpdatePipeline] 开始执行 daily update, "
            f"as_of_date={as_of_date}, "
            f"calendar_start={calendar_start}, calendar_end={calendar_end}, "
            f"repair_start={repair_start}, repair_end={repair_end}, "
            f"max_daily_dates={max_daily_dates}, "
            f"max_daily_basic_dates={max_daily_basic_dates}, "
            f"max_std_dates={max_std_dates}"
        )

        try:
            # Step 1: 刷新最近一段 trade_cal
            raw_count = self.trade_calendar_ingestor.backfill(
                start_date=calendar_start,
                end_date=calendar_end,
                exchange=settings.DEFAULT_EXCHANGE,
            )

            # Step 2: 重建 std_calendar
            std_calendar_count = self.trading_calendar_builder.build(
                exchange=settings.DEFAULT_EXCHANGE
            )

            # Step 3: 对最近窗口做补洞式回填
            self.repair_pipeline.run(
                start_date=repair_start,
                end_date=repair_end,
                mode="all",
                max_daily_dates=max_daily_dates,
                max_daily_basic_dates=max_daily_basic_dates,
                max_std_dates=max_std_dates,
            )

            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = (
                f"daily_update_v1 success, as_of_date={as_of_date}, "
                f"calendar_refresh_range={calendar_start}~{calendar_end}, "
                f"repair_range={repair_start}~{repair_end}, "
                f"trade_cal_raw_count={raw_count}, "
                f"std_calendar_count={std_calendar_count}, "
                f"max_daily_dates={max_daily_dates}, "
                f"max_daily_basic_dates={max_daily_basic_dates}, "
                f"max_std_dates={max_std_dates}"
            )

            self.job_repo.log_job_run(
                job_name="daily_update_v1",
                job_stage="calendar_refresh_and_gap_repair",
                status="SUCCESS",
                message=message,
                started_at=started_at,
                finished_at=finished_at,
            )

            self.job_logger.info(
                f"[DailyUpdatePipeline] 执行成功: {message}"
            )

        except KeyboardInterrupt:
            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = (
                f"daily_update_v1 interrupted by user, as_of_date={as_of_date}, "
                f"calendar_refresh_range={calendar_start}~{calendar_end}, "
                f"repair_range={repair_start}~{repair_end}"
            )
            self.job_repo.log_job_run(
                job_name="daily_update_v1",
                job_stage="calendar_refresh_and_gap_repair",
                status="INTERRUPTED",
                message=message,
                started_at=started_at,
                finished_at=finished_at,
            )
            self.job_logger.warning(
                f"[DailyUpdatePipeline] 已中断: {message}"
            )
            raise

        except Exception as e:
            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = (
                f"daily_update_v1 failed, as_of_date={as_of_date}, "
                f"error={type(e).__name__}: {e}"
            )
            self.job_repo.log_job_run(
                job_name="daily_update_v1",
                job_stage="calendar_refresh_and_gap_repair",
                status="FAILED",
                message=message,
                started_at=started_at,
                finished_at=finished_at,
            )
            self.error_logger.exception(
                f"[DailyUpdatePipeline] 执行失败: {message}"
            )
            raise


def main():
    parser = argparse.ArgumentParser(description="Daily Update Pipeline V1")
    parser.add_argument(
        "--as-of",
        default=None,
        help="更新基准日，格式 YYYYMMDD；默认使用当天日期",
    )
    parser.add_argument(
        "--calendar-lookback-days",
        type=int,
        default=60,
        help="刷新 trade_cal 时向前覆盖多少自然日，默认 60",
    )
    parser.add_argument(
        "--calendar-forward-days",
        type=int,
        default=30,
        help="刷新 trade_cal 时向后覆盖多少自然日，默认 30",
    )
    parser.add_argument(
        "--repair-lookback-days",
        type=int,
        default=20,
        help="补洞窗口向前覆盖多少自然日，默认 20",
    )
    parser.add_argument(
        "--max-daily-dates",
        type=int,
        default=3,
        help="本轮最多补多少个 ods_daily 缺口日期，默认 3",
    )
    parser.add_argument(
        "--max-daily-basic-dates",
        type=int,
        default=3,
        help="本轮最多补多少个 ods_daily_basic 缺口日期，默认 3",
    )
    parser.add_argument(
        "--max-std-dates",
        type=int,
        default=5,
        help="本轮最多重建多少个 std_equity_daily 日期，默认 5",
    )
    args = parser.parse_args()

    pipeline = DailyUpdatePipeline()
    pipeline.run(
        as_of_date=args.as_of,
        calendar_lookback_days=args.calendar_lookback_days,
        calendar_forward_days=args.calendar_forward_days,
        repair_lookback_days=args.repair_lookback_days,
        max_daily_dates=args.max_daily_dates,
        max_daily_basic_dates=args.max_daily_basic_dates,
        max_std_dates=args.max_std_dates,
    )


if __name__ == "__main__":
    main()