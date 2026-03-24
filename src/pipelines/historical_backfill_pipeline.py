import argparse
from datetime import datetime

from src.common.logging_utils import get_error_logger, get_job_logger
from src.config.settings import settings
from src.data_access.job_log_repository import JobLogRepository
from src.raw_ingest.adjustment_factors_ingestor import AdjustmentFactorsIngestor
from src.raw_ingest.daily_fundamentals_ingestor import DailyFundamentalsIngestor
from src.raw_ingest.daily_quotes_ingestor import DailyQuotesIngestor
from src.raw_ingest.stock_master_ingestor import StockMasterIngestor
from src.raw_ingest.trade_calendar_ingestor import TradeCalendarIngestor
from src.standardization.daily_bar_builder import DailyBarBuilder
from src.standardization.instrument_master_builder import InstrumentMasterBuilder
from src.standardization.trading_calendar_builder import TradingCalendarBuilder


class HistoricalBackfillPipeline:
    def __init__(self):
        self.trade_calendar_ingestor = TradeCalendarIngestor()
        self.trading_calendar_builder = TradingCalendarBuilder()

        self.stock_master_ingestor = StockMasterIngestor()
        self.instrument_master_builder = InstrumentMasterBuilder()

        self.daily_quotes_ingestor = DailyQuotesIngestor()
        self.daily_fundamentals_ingestor = DailyFundamentalsIngestor()
        self.adjustment_factors_ingestor = AdjustmentFactorsIngestor()

        self.daily_bar_builder = DailyBarBuilder()

        self.job_repo = JobLogRepository(settings.STD_DB_PATH)
        self.job_logger = get_job_logger()
        self.error_logger = get_error_logger()

    def run_trade_calendar(
        self,
        start_date: str,
        end_date: str,
        exchange: str | None = None,
    ) -> None:
        exchange = exchange or settings.DEFAULT_EXCHANGE
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.job_logger.info(
            f"[HistoricalBackfillPipeline] 开始执行 trade_calendar backfill, "
            f"exchange={exchange}, start_date={start_date}, end_date={end_date}"
        )

        try:
            raw_count = self.trade_calendar_ingestor.backfill(
                start_date=start_date,
                end_date=end_date,
                exchange=exchange,
            )

            std_count = self.trading_calendar_builder.build(exchange=exchange)
            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if raw_count == 0 and std_count == 0:
                message = (
                    f"trade_calendar backfill no data, raw_count={raw_count}, "
                    f"std_count={std_count}, exchange={exchange}, "
                    f"start_date={start_date}, end_date={end_date}"
                )
                self.job_repo.log_job_run(
                    job_name="historical_backfill_trade_calendar",
                    job_stage="raw_to_standardized",
                    status="NO_DATA",
                    message=message,
                    started_at=started_at,
                    finished_at=finished_at,
                )
                self.job_logger.warning(
                    f"[HistoricalBackfillPipeline] 无数据: {message}"
                )
                return

            message = (
                f"trade_calendar backfill success, raw_count={raw_count}, "
                f"std_count={std_count}, exchange={exchange}, "
                f"start_date={start_date}, end_date={end_date}"
            )

            self.job_repo.log_job_run(
                job_name="historical_backfill_trade_calendar",
                job_stage="raw_to_standardized",
                status="SUCCESS",
                message=message,
                started_at=started_at,
                finished_at=finished_at,
            )

            self.job_logger.info(
                f"[HistoricalBackfillPipeline] 执行成功: {message}"
            )

        except Exception as e:
            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = (
                f"trade_calendar backfill failed, exchange={exchange}, "
                f"start_date={start_date}, end_date={end_date}, "
                f"error={type(e).__name__}: {e}"
            )

            self.job_repo.log_job_run(
                job_name="historical_backfill_trade_calendar",
                job_stage="raw_to_standardized",
                status="FAILED",
                message=message,
                started_at=started_at,
                finished_at=finished_at,
            )

            self.error_logger.exception(
                f"[HistoricalBackfillPipeline] 执行失败: {message}"
            )
            raise

    def run_stock_basic(self) -> None:
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.job_logger.info(
            "[HistoricalBackfillPipeline] 开始执行 stock_basic backfill"
        )

        try:
            result = self.stock_master_ingestor.backfill(
                exchanges=["SSE", "SZSE", "BSE"],
                list_statuses=["L", "D", "P"],
            )

            raw_count = result["total_rows"]
            failed_slices = result["failed_slices"]
            empty_slices = result["empty_slices"]
            success_slices = result["success_slices"]

            std_count = self.instrument_master_builder.build()
            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if raw_count == 0 and std_count == 0 and failed_slices:
                message = (
                    f"stock_basic backfill failed, raw_count={raw_count}, "
                    f"std_count={std_count}, success_slices={len(success_slices)}, "
                    f"empty_slices={len(empty_slices)}, failed_slices={len(failed_slices)}, "
                    f"failed_detail={failed_slices}"
                )
                self.job_repo.log_job_run(
                    job_name="historical_backfill_stock_basic",
                    job_stage="raw_to_standardized",
                    status="FAILED",
                    message=message,
                    started_at=started_at,
                    finished_at=finished_at,
                )
                self.error_logger.error(
                    f"[HistoricalBackfillPipeline] 执行失败: {message}"
                )
                return

            if raw_count == 0 and std_count == 0 and not failed_slices:
                message = (
                    f"stock_basic backfill no data, raw_count={raw_count}, "
                    f"std_count={std_count}, success_slices={len(success_slices)}, "
                    f"empty_slices={len(empty_slices)}, failed_slices={len(failed_slices)}"
                )
                self.job_repo.log_job_run(
                    job_name="historical_backfill_stock_basic",
                    job_stage="raw_to_standardized",
                    status="NO_DATA",
                    message=message,
                    started_at=started_at,
                    finished_at=finished_at,
                )
                self.job_logger.warning(
                    f"[HistoricalBackfillPipeline] 无数据: {message}"
                )
                return

            if failed_slices:
                message = (
                    f"stock_basic backfill partial success, raw_count={raw_count}, "
                    f"std_count={std_count}, success_slices={len(success_slices)}, "
                    f"empty_slices={len(empty_slices)}, failed_slices={len(failed_slices)}, "
                    f"failed_detail={failed_slices}"
                )
                self.job_repo.log_job_run(
                    job_name="historical_backfill_stock_basic",
                    job_stage="raw_to_standardized",
                    status="PARTIAL_SUCCESS",
                    message=message,
                    started_at=started_at,
                    finished_at=finished_at,
                )
                self.job_logger.warning(
                    f"[HistoricalBackfillPipeline] 部分成功: {message}"
                )
                return

            message = (
                f"stock_basic backfill success, raw_count={raw_count}, "
                f"std_count={std_count}, success_slices={len(success_slices)}, "
                f"empty_slices={len(empty_slices)}, failed_slices={len(failed_slices)}"
            )

            self.job_repo.log_job_run(
                job_name="historical_backfill_stock_basic",
                job_stage="raw_to_standardized",
                status="SUCCESS",
                message=message,
                started_at=started_at,
                finished_at=finished_at,
            )

            self.job_logger.info(
                f"[HistoricalBackfillPipeline] 执行成功: {message}"
            )

        except Exception as e:
            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = (
                f"stock_basic backfill failed by pipeline exception, "
                f"error={type(e).__name__}: {e}"
            )

            self.job_repo.log_job_run(
                job_name="historical_backfill_stock_basic",
                job_stage="raw_to_standardized",
                status="FAILED",
                message=message,
                started_at=started_at,
                finished_at=finished_at,
            )

            self.error_logger.exception(
                f"[HistoricalBackfillPipeline] 执行失败: {message}"
            )
            raise

    def run_daily_quotes(
        self,
        start_date: str,
        end_date: str,
        max_trade_days: int | None = None,
    ) -> None:
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.job_logger.info(
            f"[HistoricalBackfillPipeline] 开始执行 daily_quotes backfill, "
            f"start_date={start_date}, end_date={end_date}, max_trade_days={max_trade_days}"
        )

        try:
            result = self.daily_quotes_ingestor.backfill(
                start_date=start_date,
                end_date=end_date,
                max_trade_days=max_trade_days,
            )

            raw_count = result["total_rows"]
            failed_slices = result["failed_slices"]
            empty_slices = result["empty_slices"]
            success_slices = result["success_slices"]
            total_trade_dates = result["total_trade_dates"]
            processed_trade_dates = result["processed_trade_dates"]

            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if raw_count == 0 and failed_slices:
                message = (
                    f"daily_quotes backfill failed, raw_count={raw_count}, "
                    f"success_slices={len(success_slices)}, empty_slices={len(empty_slices)}, "
                    f"failed_slices={len(failed_slices)}, total_trade_dates={total_trade_dates}, "
                    f"processed_trade_dates={processed_trade_dates}, "
                    f"failed_detail={failed_slices[:10]}"
                )
                self.job_repo.log_job_run(
                    job_name="historical_backfill_daily_quotes",
                    job_stage="raw_only",
                    status="FAILED",
                    message=message,
                    started_at=started_at,
                    finished_at=finished_at,
                )
                self.error_logger.error(
                    f"[HistoricalBackfillPipeline] 执行失败: {message}"
                )
                return

            if raw_count == 0 and not failed_slices:
                message = (
                    f"daily_quotes backfill no data, raw_count={raw_count}, "
                    f"success_slices={len(success_slices)}, empty_slices={len(empty_slices)}, "
                    f"failed_slices={len(failed_slices)}, total_trade_dates={total_trade_dates}, "
                    f"processed_trade_dates={processed_trade_dates}"
                )
                self.job_repo.log_job_run(
                    job_name="historical_backfill_daily_quotes",
                    job_stage="raw_only",
                    status="NO_DATA",
                    message=message,
                    started_at=started_at,
                    finished_at=finished_at,
                )
                self.job_logger.warning(
                    f"[HistoricalBackfillPipeline] 无数据: {message}"
                )
                return

            if failed_slices:
                message = (
                    f"daily_quotes backfill partial success, raw_count={raw_count}, "
                    f"success_slices={len(success_slices)}, empty_slices={len(empty_slices)}, "
                    f"failed_slices={len(failed_slices)}, total_trade_dates={total_trade_dates}, "
                    f"processed_trade_dates={processed_trade_dates}, "
                    f"failed_detail={failed_slices[:10]}"
                )
                self.job_repo.log_job_run(
                    job_name="historical_backfill_daily_quotes",
                    job_stage="raw_only",
                    status="PARTIAL_SUCCESS",
                    message=message,
                    started_at=started_at,
                    finished_at=finished_at,
                )
                self.job_logger.warning(
                    f"[HistoricalBackfillPipeline] 部分成功: {message}"
                )
                return

            message = (
                f"daily_quotes backfill success, raw_count={raw_count}, "
                f"success_slices={len(success_slices)}, empty_slices={len(empty_slices)}, "
                f"failed_slices={len(failed_slices)}, total_trade_dates={total_trade_dates}, "
                f"processed_trade_dates={processed_trade_dates}"
            )

            self.job_repo.log_job_run(
                job_name="historical_backfill_daily_quotes",
                job_stage="raw_only",
                status="SUCCESS",
                message=message,
                started_at=started_at,
                finished_at=finished_at,
            )

            self.job_logger.info(
                f"[HistoricalBackfillPipeline] 执行成功: {message}"
            )

        except KeyboardInterrupt:
            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = (
                f"daily_quotes backfill interrupted by user, "
                f"start_date={start_date}, end_date={end_date}, max_trade_days={max_trade_days}"
            )
            self.job_repo.log_job_run(
                job_name="historical_backfill_daily_quotes",
                job_stage="raw_only",
                status="INTERRUPTED",
                message=message,
                started_at=started_at,
                finished_at=finished_at,
            )
            self.job_logger.warning(
                f"[HistoricalBackfillPipeline] 已中断: {message}"
            )
            raise

        except Exception as e:
            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = (
                f"daily_quotes backfill failed by pipeline exception, "
                f"error={type(e).__name__}: {e}"
            )

            self.job_repo.log_job_run(
                job_name="historical_backfill_daily_quotes",
                job_stage="raw_only",
                status="FAILED",
                message=message,
                started_at=started_at,
                finished_at=finished_at,
            )

            self.error_logger.exception(
                f"[HistoricalBackfillPipeline] 执行失败: {message}"
            )
            raise

    def run_daily_fundamentals(
        self,
        start_date: str,
        end_date: str,
        max_trade_days: int | None = None,
    ) -> None:
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.job_logger.info(
            f"[HistoricalBackfillPipeline] 开始执行 daily_fundamentals backfill, "
            f"start_date={start_date}, end_date={end_date}, max_trade_days={max_trade_days}"
        )

        try:
            result = self.daily_fundamentals_ingestor.backfill(
                start_date=start_date,
                end_date=end_date,
                max_trade_days=max_trade_days,
            )

            raw_count = result["total_rows"]
            failed_slices = result["failed_slices"]
            empty_slices = result["empty_slices"]
            success_slices = result["success_slices"]
            total_trade_dates = result["total_trade_dates"]
            processed_trade_dates = result["processed_trade_dates"]

            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if raw_count == 0 and failed_slices:
                message = (
                    f"daily_fundamentals backfill failed, raw_count={raw_count}, "
                    f"success_slices={len(success_slices)}, empty_slices={len(empty_slices)}, "
                    f"failed_slices={len(failed_slices)}, total_trade_dates={total_trade_dates}, "
                    f"processed_trade_dates={processed_trade_dates}, "
                    f"failed_detail={failed_slices[:10]}"
                )
                self.job_repo.log_job_run(
                    job_name="historical_backfill_daily_fundamentals",
                    job_stage="raw_only",
                    status="FAILED",
                    message=message,
                    started_at=started_at,
                    finished_at=finished_at,
                )
                self.error_logger.error(
                    f"[HistoricalBackfillPipeline] 执行失败: {message}"
                )
                return

            if raw_count == 0 and not failed_slices:
                message = (
                    f"daily_fundamentals backfill no data, raw_count={raw_count}, "
                    f"success_slices={len(success_slices)}, empty_slices={len(empty_slices)}, "
                    f"failed_slices={len(failed_slices)}, total_trade_dates={total_trade_dates}, "
                    f"processed_trade_dates={processed_trade_dates}"
                )
                self.job_repo.log_job_run(
                    job_name="historical_backfill_daily_fundamentals",
                    job_stage="raw_only",
                    status="NO_DATA",
                    message=message,
                    started_at=started_at,
                    finished_at=finished_at,
                )
                self.job_logger.warning(
                    f"[HistoricalBackfillPipeline] 无数据: {message}"
                )
                return

            if failed_slices:
                message = (
                    f"daily_fundamentals backfill partial success, raw_count={raw_count}, "
                    f"success_slices={len(success_slices)}, empty_slices={len(empty_slices)}, "
                    f"failed_slices={len(failed_slices)}, total_trade_dates={total_trade_dates}, "
                    f"processed_trade_dates={processed_trade_dates}, "
                    f"failed_detail={failed_slices[:10]}"
                )
                self.job_repo.log_job_run(
                    job_name="historical_backfill_daily_fundamentals",
                    job_stage="raw_only",
                    status="PARTIAL_SUCCESS",
                    message=message,
                    started_at=started_at,
                    finished_at=finished_at,
                )
                self.job_logger.warning(
                    f"[HistoricalBackfillPipeline] 部分成功: {message}"
                )
                return

            message = (
                f"daily_fundamentals backfill success, raw_count={raw_count}, "
                f"success_slices={len(success_slices)}, empty_slices={len(empty_slices)}, "
                f"failed_slices={len(failed_slices)}, total_trade_dates={total_trade_dates}, "
                f"processed_trade_dates={processed_trade_dates}"
            )

            self.job_repo.log_job_run(
                job_name="historical_backfill_daily_fundamentals",
                job_stage="raw_only",
                status="SUCCESS",
                message=message,
                started_at=started_at,
                finished_at=finished_at,
            )

            self.job_logger.info(
                f"[HistoricalBackfillPipeline] 执行成功: {message}"
            )

        except KeyboardInterrupt:
            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = (
                f"daily_fundamentals backfill interrupted by user, "
                f"start_date={start_date}, end_date={end_date}, max_trade_days={max_trade_days}"
            )
            self.job_repo.log_job_run(
                job_name="historical_backfill_daily_fundamentals",
                job_stage="raw_only",
                status="INTERRUPTED",
                message=message,
                started_at=started_at,
                finished_at=finished_at,
            )
            self.job_logger.warning(
                f"[HistoricalBackfillPipeline] 已中断: {message}"
            )
            raise

        except Exception as e:
            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = (
                f"daily_fundamentals backfill failed by pipeline exception, "
                f"error={type(e).__name__}: {e}"
            )

            self.job_repo.log_job_run(
                job_name="historical_backfill_daily_fundamentals",
                job_stage="raw_only",
                status="FAILED",
                message=message,
                started_at=started_at,
                finished_at=finished_at,
            )

            self.error_logger.exception(
                f"[HistoricalBackfillPipeline] 执行失败: {message}"
            )
            raise

    def run_adjustment_factors(
        self,
        start_date: str,
        end_date: str,
        max_trade_days: int | None = None,
    ) -> None:
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.job_logger.info(
            f"[HistoricalBackfillPipeline] 开始执行 adjustment_factors backfill, "
            f"start_date={start_date}, end_date={end_date}, max_trade_days={max_trade_days}"
        )

        try:
            result = self.adjustment_factors_ingestor.backfill(
                start_date=start_date,
                end_date=end_date,
                max_trade_days=max_trade_days,
            )

            raw_count = result["total_rows"]
            failed_slices = result["failed_slices"]
            empty_slices = result["empty_slices"]
            success_slices = result["success_slices"]
            total_trade_dates = result["total_trade_dates"]
            processed_trade_dates = result["processed_trade_dates"]

            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if raw_count == 0 and failed_slices:
                message = (
                    f"adjustment_factors backfill failed, raw_count={raw_count}, "
                    f"success_slices={len(success_slices)}, empty_slices={len(empty_slices)}, "
                    f"failed_slices={len(failed_slices)}, total_trade_dates={total_trade_dates}, "
                    f"processed_trade_dates={processed_trade_dates}, "
                    f"failed_detail={failed_slices[:10]}"
                )
                self.job_repo.log_job_run(
                    job_name="historical_backfill_adjustment_factors",
                    job_stage="raw_only",
                    status="FAILED",
                    message=message,
                    started_at=started_at,
                    finished_at=finished_at,
                )
                self.error_logger.error(
                    f"[HistoricalBackfillPipeline] 执行失败: {message}"
                )
                return

            if raw_count == 0 and not failed_slices:
                message = (
                    f"adjustment_factors backfill no data, raw_count={raw_count}, "
                    f"success_slices={len(success_slices)}, empty_slices={len(empty_slices)}, "
                    f"failed_slices={len(failed_slices)}, total_trade_dates={total_trade_dates}, "
                    f"processed_trade_dates={processed_trade_dates}"
                )
                self.job_repo.log_job_run(
                    job_name="historical_backfill_adjustment_factors",
                    job_stage="raw_only",
                    status="NO_DATA",
                    message=message,
                    started_at=started_at,
                    finished_at=finished_at,
                )
                self.job_logger.warning(
                    f"[HistoricalBackfillPipeline] 无数据: {message}"
                )
                return

            if failed_slices:
                message = (
                    f"adjustment_factors backfill partial success, raw_count={raw_count}, "
                    f"success_slices={len(success_slices)}, empty_slices={len(empty_slices)}, "
                    f"failed_slices={len(failed_slices)}, total_trade_dates={total_trade_dates}, "
                    f"processed_trade_dates={processed_trade_dates}, "
                    f"failed_detail={failed_slices[:10]}"
                )
                self.job_repo.log_job_run(
                    job_name="historical_backfill_adjustment_factors",
                    job_stage="raw_only",
                    status="PARTIAL_SUCCESS",
                    message=message,
                    started_at=started_at,
                    finished_at=finished_at,
                )
                self.job_logger.warning(
                    f"[HistoricalBackfillPipeline] 部分成功: {message}"
                )
                return

            message = (
                f"adjustment_factors backfill success, raw_count={raw_count}, "
                f"success_slices={len(success_slices)}, empty_slices={len(empty_slices)}, "
                f"failed_slices={len(failed_slices)}, total_trade_dates={total_trade_dates}, "
                f"processed_trade_dates={processed_trade_dates}"
            )

            self.job_repo.log_job_run(
                job_name="historical_backfill_adjustment_factors",
                job_stage="raw_only",
                status="SUCCESS",
                message=message,
                started_at=started_at,
                finished_at=finished_at,
            )

            self.job_logger.info(
                f"[HistoricalBackfillPipeline] 执行成功: {message}"
            )

        except KeyboardInterrupt:
            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = (
                f"adjustment_factors backfill interrupted by user, "
                f"start_date={start_date}, end_date={end_date}, max_trade_days={max_trade_days}"
            )
            self.job_repo.log_job_run(
                job_name="historical_backfill_adjustment_factors",
                job_stage="raw_only",
                status="INTERRUPTED",
                message=message,
                started_at=started_at,
                finished_at=finished_at,
            )
            self.job_logger.warning(
                f"[HistoricalBackfillPipeline] 已中断: {message}"
            )
            raise

        except Exception as e:
            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = (
                f"adjustment_factors backfill failed by pipeline exception, "
                f"error={type(e).__name__}: {e}"
            )

            self.job_repo.log_job_run(
                job_name="historical_backfill_adjustment_factors",
                job_stage="raw_only",
                status="FAILED",
                message=message,
                started_at=started_at,
                finished_at=finished_at,
            )

            self.error_logger.exception(
                f"[HistoricalBackfillPipeline] 执行失败: {message}"
            )
            raise

    def run_build_std_equity_daily(
        self,
        start_date: str,
        end_date: str,
        max_trade_days: int | None = None,
    ) -> None:
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.job_logger.info(
            f"[HistoricalBackfillPipeline] 开始构建 std_equity_daily, "
            f"start_date={start_date}, end_date={end_date}, max_trade_days={max_trade_days}"
        )

        try:
            result = self.daily_bar_builder.build(
                start_date=start_date,
                end_date=end_date,
                max_trade_days=max_trade_days,
            )

            std_count = result["total_rows"]
            failed_slices = result["failed_slices"]
            empty_slices = result["empty_slices"]
            success_slices = result["success_slices"]
            total_trade_dates = result["total_trade_dates"]
            processed_trade_dates = result["processed_trade_dates"]

            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if std_count == 0 and failed_slices:
                message = (
                    f"build_std_equity_daily failed, std_count={std_count}, "
                    f"success_slices={len(success_slices)}, empty_slices={len(empty_slices)}, "
                    f"failed_slices={len(failed_slices)}, total_trade_dates={total_trade_dates}, "
                    f"processed_trade_dates={processed_trade_dates}, "
                    f"failed_detail={failed_slices[:10]}"
                )
                self.job_repo.log_job_run(
                    job_name="build_std_equity_daily",
                    job_stage="standardized_only",
                    status="FAILED",
                    message=message,
                    started_at=started_at,
                    finished_at=finished_at,
                )
                self.error_logger.error(
                    f"[HistoricalBackfillPipeline] 执行失败: {message}"
                )
                return

            if std_count == 0 and not failed_slices:
                message = (
                    f"build_std_equity_daily no data, std_count={std_count}, "
                    f"success_slices={len(success_slices)}, empty_slices={len(empty_slices)}, "
                    f"failed_slices={len(failed_slices)}, total_trade_dates={total_trade_dates}, "
                    f"processed_trade_dates={processed_trade_dates}"
                )
                self.job_repo.log_job_run(
                    job_name="build_std_equity_daily",
                    job_stage="standardized_only",
                    status="NO_DATA",
                    message=message,
                    started_at=started_at,
                    finished_at=finished_at,
                )
                self.job_logger.warning(
                    f"[HistoricalBackfillPipeline] 无数据: {message}"
                )
                return

            if failed_slices:
                message = (
                    f"build_std_equity_daily partial success, std_count={std_count}, "
                    f"success_slices={len(success_slices)}, empty_slices={len(empty_slices)}, "
                    f"failed_slices={len(failed_slices)}, total_trade_dates={total_trade_dates}, "
                    f"processed_trade_dates={processed_trade_dates}, "
                    f"failed_detail={failed_slices[:10]}"
                )
                self.job_repo.log_job_run(
                    job_name="build_std_equity_daily",
                    job_stage="standardized_only",
                    status="PARTIAL_SUCCESS",
                    message=message,
                    started_at=started_at,
                    finished_at=finished_at,
                )
                self.job_logger.warning(
                    f"[HistoricalBackfillPipeline] 部分成功: {message}"
                )
                return

            message = (
                f"build_std_equity_daily success, std_count={std_count}, "
                f"success_slices={len(success_slices)}, empty_slices={len(empty_slices)}, "
                f"failed_slices={len(failed_slices)}, total_trade_dates={total_trade_dates}, "
                f"processed_trade_dates={processed_trade_dates}"
            )

            self.job_repo.log_job_run(
                job_name="build_std_equity_daily",
                job_stage="standardized_only",
                status="SUCCESS",
                message=message,
                started_at=started_at,
                finished_at=finished_at,
            )

            self.job_logger.info(
                f"[HistoricalBackfillPipeline] 执行成功: {message}"
            )

        except KeyboardInterrupt:
            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = (
                f"build_std_equity_daily interrupted by user, "
                f"start_date={start_date}, end_date={end_date}, max_trade_days={max_trade_days}"
            )
            self.job_repo.log_job_run(
                job_name="build_std_equity_daily",
                job_stage="standardized_only",
                status="INTERRUPTED",
                message=message,
                started_at=started_at,
                finished_at=finished_at,
            )
            self.job_logger.warning(
                f"[HistoricalBackfillPipeline] 已中断: {message}"
            )
            raise

        except Exception as e:
            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = (
                f"build_std_equity_daily failed by pipeline exception, "
                f"error={type(e).__name__}: {e}"
            )

            self.job_repo.log_job_run(
                job_name="build_std_equity_daily",
                job_stage="standardized_only",
                status="FAILED",
                message=message,
                started_at=started_at,
                finished_at=finished_at,
            )

            self.error_logger.exception(
                f"[HistoricalBackfillPipeline] 执行失败: {message}"
            )
            raise


def main():
    parser = argparse.ArgumentParser(description="Historical Backfill Pipeline")
    parser.add_argument(
        "--task",
        choices=[
            "trade_calendar",
            "stock_basic",
            "daily_quotes",
            "daily_fundamentals",
            "adjustment_factors",
            "build_std_equity_daily",
        ],
        required=True,
        help="执行的回填任务",
    )
    parser.add_argument("--start", default=settings.DEFAULT_START_DATE, help="开始日期，例如 20240101")
    parser.add_argument("--end", default=settings.DEFAULT_END_DATE, help="结束日期，例如 20260331")
    parser.add_argument(
        "--calendar-exchange",
        default=settings.DEFAULT_EXCHANGE,
        help="trade_calendar 使用的交易所，默认 SSE",
    )
    parser.add_argument(
        "--max-trade-days",
        type=int,
        default=None,
        help="日频任务本次最多处理多少个交易日，建议先用 1 / 3 / 5 做小批回填",
    )
    args = parser.parse_args()

    pipeline = HistoricalBackfillPipeline()

    if args.task == "trade_calendar":
        pipeline.run_trade_calendar(
            start_date=args.start,
            end_date=args.end,
            exchange=args.calendar_exchange,
        )
    elif args.task == "stock_basic":
        pipeline.run_stock_basic()
    elif args.task == "daily_quotes":
        pipeline.run_daily_quotes(
            start_date=args.start,
            end_date=args.end,
            max_trade_days=args.max_trade_days,
        )
    elif args.task == "daily_fundamentals":
        pipeline.run_daily_fundamentals(
            start_date=args.start,
            end_date=args.end,
            max_trade_days=args.max_trade_days,
        )
    elif args.task == "adjustment_factors":
        pipeline.run_adjustment_factors(
            start_date=args.start,
            end_date=args.end,
            max_trade_days=args.max_trade_days,
        )
    elif args.task == "build_std_equity_daily":
        pipeline.run_build_std_equity_daily(
            start_date=args.start,
            end_date=args.end,
            max_trade_days=args.max_trade_days,
        )


if __name__ == "__main__":
    main()