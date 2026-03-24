import argparse
import sqlite3
from datetime import datetime

import pandas as pd

from src.common.logging_utils import get_app_logger, get_error_logger, get_job_logger
from src.config.settings import settings
from src.data_access.job_log_repository import JobLogRepository
from src.raw_ingest.daily_fundamentals_ingestor import DailyFundamentalsIngestor
from src.raw_ingest.daily_quotes_ingestor import DailyQuotesIngestor
from src.standardization.daily_bar_builder import DailyBarBuilder


def _yyyymmdd_to_iso(date_str: str) -> str:
    s = str(date_str)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def _iso_to_yyyymmdd(date_str: str) -> str:
    return str(date_str).replace("-", "")


class RepairDailyGapsPipeline:
    def __init__(self):
        self.raw_db_path = settings.RAW_DB_PATH
        self.std_db_path = settings.STD_DB_PATH

        self.daily_quotes_ingestor = DailyQuotesIngestor()
        self.daily_fundamentals_ingestor = DailyFundamentalsIngestor()
        self.daily_bar_builder = DailyBarBuilder()

        self.job_repo = JobLogRepository(settings.STD_DB_PATH)
        self.app_logger = get_app_logger()
        self.job_logger = get_job_logger()
        self.error_logger = get_error_logger()

    def _fetch_open_trade_dates(self, start_date: str, end_date: str) -> list[str]:
        start_iso = _yyyymmdd_to_iso(start_date)
        end_iso = _yyyymmdd_to_iso(end_date)

        conn = sqlite3.connect(self.std_db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT trade_date
                FROM std_calendar
                WHERE is_open = 1
                  AND trade_date >= ?
                  AND trade_date <= ?
                ORDER BY trade_date;
                """,
                (start_iso, end_iso),
            ).fetchall()
        finally:
            conn.close()

        return [row["trade_date"] for row in rows]

    def _count_rows_raw(self, conn: sqlite3.Connection, table_name: str, trade_date_raw: str) -> int:
        row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM {table_name} WHERE trade_date = ?;",
            (trade_date_raw,),
        ).fetchone()
        return int(row[0]) if row else 0

    def _count_rows_std(self, conn: sqlite3.Connection, table_name: str, trade_date_iso: str) -> int:
        row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM {table_name} WHERE trade_date = ?;",
            (trade_date_iso,),
        ).fetchone()
        return int(row[0]) if row else 0

    def _build_audit_df(self, start_date: str, end_date: str) -> pd.DataFrame:
        trade_dates_iso = self._fetch_open_trade_dates(start_date, end_date)

        raw_conn = sqlite3.connect(self.raw_db_path)
        std_conn = sqlite3.connect(self.std_db_path)

        try:
            records = []

            for trade_date_iso in trade_dates_iso:
                trade_date_raw = _iso_to_yyyymmdd(trade_date_iso)

                ods_daily_cnt = self._count_rows_raw(raw_conn, "ods_daily", trade_date_raw)
                ods_daily_basic_cnt = self._count_rows_raw(raw_conn, "ods_daily_basic", trade_date_raw)
                ods_adj_factor_cnt = self._count_rows_raw(raw_conn, "ods_adj_factor", trade_date_raw)
                std_equity_daily_cnt = self._count_rows_std(std_conn, "std_equity_daily", trade_date_iso)

                record = {
                    "trade_date_raw": trade_date_raw,
                    "trade_date_iso": trade_date_iso,
                    "ods_daily_count": ods_daily_cnt,
                    "ods_daily_basic_count": ods_daily_basic_cnt,
                    "ods_adj_factor_count": ods_adj_factor_cnt,
                    "std_equity_daily_count": std_equity_daily_cnt,
                    "has_ods_daily": int(ods_daily_cnt > 0),
                    "has_ods_daily_basic": int(ods_daily_basic_cnt > 0),
                    "has_ods_adj_factor": int(ods_adj_factor_cnt > 0),
                    "has_std_equity_daily": int(std_equity_daily_cnt > 0),
                }

                # 当前桥梁层仍遵循既有设计：
                # std_equity_daily 的构建条件只要求 ods_daily + ods_adj_factor
                # daily_basic 允许为空，后续再通过重建补齐估值类字段
                record["ready_for_std_build"] = int(
                    record["has_ods_daily"] == 1 and record["has_ods_adj_factor"] == 1
                )

                records.append(record)

            return pd.DataFrame(records)

        finally:
            raw_conn.close()
            std_conn.close()

    def _limit_dates(self, dates: list[str], max_n: int | None) -> list[str]:
        if max_n is None or max_n <= 0:
            return dates
        return dates[:max_n]

    def _unique_keep_order(self, dates: list[str]) -> list[str]:
        seen = set()
        result = []
        for d in dates:
            if d and d not in seen:
                seen.add(d)
                result.append(d)
        return result

    def _select_std_dates(
        self,
        audit_df: pd.DataFrame,
        touched_daily_dates: list[str],
        touched_daily_basic_dates: list[str],
        max_std_dates: int | None,
    ) -> list[str]:
        """
        std 目标日期选择策略（修正版）：

        优先级 1：
        - 真正缺失 std_equity_daily
        - 且已经具备构建条件（ods_daily + ods_adj_factor）

        优先级 2：
        - 本轮刚刚被 daily / daily_basic 修过
        - 且当前已经具备构建条件
        - 即使 std 已存在，也允许重建，用于补齐后来补进来的 daily_basic 字段

        优先级 3：
        - 其他已具备构建条件、且已有 std 的日期（仅在前两类不足 max_std_dates 时作为补位）
        """

        ready_df = audit_df.loc[audit_df["ready_for_std_build"] == 1].copy()

        missing_ready_std_dates = ready_df.loc[
            ready_df["has_std_equity_daily"] == 0, "trade_date_raw"
        ].tolist()

        touched_dates = self._unique_keep_order(touched_daily_dates + touched_daily_basic_dates)

        touched_existing_std_dates = ready_df.loc[
            (ready_df["has_std_equity_daily"] == 1)
            & (ready_df["trade_date_raw"].isin(touched_dates)),
            "trade_date_raw",
        ].tolist()

        other_existing_ready_std_dates = ready_df.loc[
            (ready_df["has_std_equity_daily"] == 1)
            & (~ready_df["trade_date_raw"].isin(touched_dates)),
            "trade_date_raw",
        ].tolist()

        prioritized_dates = self._unique_keep_order(
            missing_ready_std_dates
            + touched_existing_std_dates
            + other_existing_ready_std_dates
        )

        return self._limit_dates(prioritized_dates, max_std_dates)

    def _repair_daily_dates(self, dates: list[str]) -> dict:
        success_dates = []
        failed_dates = []

        for trade_date in dates:
            try:
                result = self.daily_quotes_ingestor.backfill(
                    start_date=trade_date,
                    end_date=trade_date,
                    max_trade_days=1,
                )
                if result["total_rows"] > 0:
                    success_dates.append(trade_date)
                else:
                    failed_dates.append(
                        {"trade_date": trade_date, "reason": "no_rows_written"}
                    )
            except Exception as e:
                failed_dates.append(
                    {
                        "trade_date": trade_date,
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    }
                )

        return {
            "success_dates": success_dates,
            "failed_dates": failed_dates,
        }

    def _repair_daily_basic_dates(self, dates: list[str]) -> dict:
        success_dates = []
        failed_dates = []

        for trade_date in dates:
            try:
                result = self.daily_fundamentals_ingestor.backfill(
                    start_date=trade_date,
                    end_date=trade_date,
                    max_trade_days=1,
                )
                if result["total_rows"] > 0:
                    success_dates.append(trade_date)
                else:
                    failed_dates.append(
                        {"trade_date": trade_date, "reason": "no_rows_written"}
                    )
            except Exception as e:
                failed_dates.append(
                    {
                        "trade_date": trade_date,
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    }
                )

        return {
            "success_dates": success_dates,
            "failed_dates": failed_dates,
        }

    def _rebuild_std_dates(self, dates: list[str]) -> dict:
        success_dates = []
        failed_dates = []
        empty_dates = []

        for trade_date in dates:
            try:
                result = self.daily_bar_builder.build(
                    start_date=trade_date,
                    end_date=trade_date,
                    max_trade_days=1,
                )

                if result["total_rows"] > 0:
                    success_dates.append(trade_date)
                elif result["empty_slices"]:
                    empty_dates.append(trade_date)
                else:
                    failed_dates.append(
                        {"trade_date": trade_date, "reason": "std_build_zero_rows"}
                    )
            except Exception as e:
                failed_dates.append(
                    {
                        "trade_date": trade_date,
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    }
                )

        return {
            "success_dates": success_dates,
            "empty_dates": empty_dates,
            "failed_dates": failed_dates,
        }

    def run(
        self,
        start_date: str,
        end_date: str,
        mode: str = "all",
        max_daily_dates: int | None = 3,
        max_daily_basic_dates: int | None = 3,
        max_std_dates: int | None = 5,
    ) -> None:
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.job_logger.info(
            f"[RepairDailyGapsPipeline] 开始执行 repair, "
            f"start_date={start_date}, end_date={end_date}, "
            f"mode={mode}, max_daily_dates={max_daily_dates}, "
            f"max_daily_basic_dates={max_daily_basic_dates}, max_std_dates={max_std_dates}"
        )

        try:
            before_df = self._build_audit_df(start_date, end_date)

            missing_daily_dates = before_df.loc[
                before_df["has_ods_daily"] == 0, "trade_date_raw"
            ].tolist()

            missing_daily_basic_dates = before_df.loc[
                before_df["has_ods_daily_basic"] == 0, "trade_date_raw"
            ].tolist()

            selected_daily_dates = []
            selected_daily_basic_dates = []
            selected_std_dates = []

            daily_result = {"success_dates": [], "failed_dates": []}
            daily_basic_result = {"success_dates": [], "failed_dates": []}
            std_result = {"success_dates": [], "empty_dates": [], "failed_dates": []}

            if mode in ("all", "daily"):
                selected_daily_dates = self._limit_dates(missing_daily_dates, max_daily_dates)
                self.job_logger.info(
                    f"[RepairDailyGapsPipeline] 本轮待修复 ods_daily 日期: {selected_daily_dates}"
                )
                daily_result = self._repair_daily_dates(selected_daily_dates)

            if mode in ("all", "daily_basic"):
                refreshed_df = self._build_audit_df(start_date, end_date)
                missing_daily_basic_dates = refreshed_df.loc[
                    refreshed_df["has_ods_daily_basic"] == 0, "trade_date_raw"
                ].tolist()

                selected_daily_basic_dates = self._limit_dates(
                    missing_daily_basic_dates,
                    max_daily_basic_dates,
                )

                self.job_logger.info(
                    f"[RepairDailyGapsPipeline] 本轮待修复 ods_daily_basic 日期: {selected_daily_basic_dates}"
                )
                daily_basic_result = self._repair_daily_basic_dates(selected_daily_basic_dates)

            if mode in ("all", "std"):
                refreshed_df = self._build_audit_df(start_date, end_date)

                selected_std_dates = self._select_std_dates(
                    audit_df=refreshed_df,
                    touched_daily_dates=selected_daily_dates,
                    touched_daily_basic_dates=selected_daily_basic_dates,
                    max_std_dates=max_std_dates,
                )

                self.job_logger.info(
                    f"[RepairDailyGapsPipeline] 本轮待重建 std_equity_daily 日期: {selected_std_dates}"
                )
                std_result = self._rebuild_std_dates(selected_std_dates)

            after_df = self._build_audit_df(start_date, end_date)

            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            remaining_missing_daily = after_df.loc[
                after_df["has_ods_daily"] == 0, "trade_date_raw"
            ].tolist()

            remaining_missing_daily_basic = after_df.loc[
                after_df["has_ods_daily_basic"] == 0, "trade_date_raw"
            ].tolist()

            remaining_missing_std = after_df.loc[
                after_df["has_std_equity_daily"] == 0, "trade_date_raw"
            ].tolist()

            failed_total = (
                len(daily_result["failed_dates"])
                + len(daily_basic_result["failed_dates"])
                + len(std_result["failed_dates"])
            )

            success_total = (
                len(daily_result["success_dates"])
                + len(daily_basic_result["success_dates"])
                + len(std_result["success_dates"])
            )

            message = (
                f"repair_daily_gaps finished, mode={mode}, "
                f"selected_daily_dates={selected_daily_dates}, "
                f"selected_daily_basic_dates={selected_daily_basic_dates}, "
                f"selected_std_dates={selected_std_dates}, "
                f"daily_success={daily_result['success_dates']}, "
                f"daily_failed={daily_result['failed_dates']}, "
                f"daily_basic_success={daily_basic_result['success_dates']}, "
                f"daily_basic_failed={daily_basic_result['failed_dates']}, "
                f"std_success={std_result['success_dates']}, "
                f"std_empty={std_result['empty_dates']}, "
                f"std_failed={std_result['failed_dates']}, "
                f"remaining_missing_daily={remaining_missing_daily[:20]}, "
                f"remaining_missing_daily_basic={remaining_missing_daily_basic[:20]}, "
                f"remaining_missing_std={remaining_missing_std[:20]}"
            )

            if success_total == 0 and failed_total == 0:
                status = "NO_DATA"
            elif failed_total > 0 and success_total == 0:
                status = "FAILED"
            elif failed_total > 0:
                status = "PARTIAL_SUCCESS"
            else:
                status = "SUCCESS"

            self.job_repo.log_job_run(
                job_name="repair_daily_gaps",
                job_stage="repair_and_rebuild",
                status=status,
                message=message,
                started_at=started_at,
                finished_at=finished_at,
            )

            print("=" * 90)
            print("补洞式回填完成")
            print(f"模式: {mode}")
            print(f"状态: {status}")
            print("-" * 90)
            print("本轮修复目标：")
            print("  ods_daily:", selected_daily_dates)
            print("  ods_daily_basic:", selected_daily_basic_dates)
            print("  std_equity_daily:", selected_std_dates)
            print("-" * 90)
            print("本轮修复结果：")
            print("  daily 成功:", daily_result["success_dates"])
            print("  daily 失败:", daily_result["failed_dates"])
            print("  daily_basic 成功:", daily_basic_result["success_dates"])
            print("  daily_basic 失败:", daily_basic_result["failed_dates"])
            print("  std 成功:", std_result["success_dates"])
            print("  std 空结果:", std_result["empty_dates"])
            print("  std 失败:", std_result["failed_dates"])
            print("-" * 90)
            print("修复后剩余缺口：")
            print("  剩余缺 ods_daily:", remaining_missing_daily[:20])
            print("  剩余缺 ods_daily_basic:", remaining_missing_daily_basic[:20])
            print("  剩余缺 std_equity_daily:", remaining_missing_std[:20])
            print("=" * 90)

        except KeyboardInterrupt:
            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = (
                f"repair_daily_gaps interrupted by user, mode={mode}, "
                f"start_date={start_date}, end_date={end_date}"
            )
            self.job_repo.log_job_run(
                job_name="repair_daily_gaps",
                job_stage="repair_and_rebuild",
                status="INTERRUPTED",
                message=message,
                started_at=started_at,
                finished_at=finished_at,
            )
            self.job_logger.warning(
                f"[RepairDailyGapsPipeline] 已中断: {message}"
            )
            raise

        except Exception as e:
            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = (
                f"repair_daily_gaps failed, mode={mode}, "
                f"error={type(e).__name__}: {e}"
            )
            self.job_repo.log_job_run(
                job_name="repair_daily_gaps",
                job_stage="repair_and_rebuild",
                status="FAILED",
                message=message,
                started_at=started_at,
                finished_at=finished_at,
            )
            self.error_logger.exception(
                f"[RepairDailyGapsPipeline] 执行失败: {message}"
            )
            raise


def main():
    parser = argparse.ArgumentParser(description="Repair Daily Gaps Pipeline")
    parser.add_argument("--start", required=True, help="开始日期，例如 20240101")
    parser.add_argument("--end", required=True, help="结束日期，例如 20240131")
    parser.add_argument(
        "--mode",
        choices=["all", "daily", "daily_basic", "std"],
        default="all",
        help="修复模式：all / daily / daily_basic / std",
    )
    parser.add_argument(
        "--max-daily-dates",
        type=int,
        default=3,
        help="本轮最多修复多少个 ods_daily 缺口日期，建议先用 3",
    )
    parser.add_argument(
        "--max-daily-basic-dates",
        type=int,
        default=3,
        help="本轮最多修复多少个 ods_daily_basic 缺口日期，建议先用 3",
    )
    parser.add_argument(
        "--max-std-dates",
        type=int,
        default=5,
        help="本轮最多重建多少个 std_equity_daily 日期，建议先用 5",
    )
    args = parser.parse_args()

    pipeline = RepairDailyGapsPipeline()
    pipeline.run(
        start_date=args.start,
        end_date=args.end,
        mode=args.mode,
        max_daily_dates=args.max_daily_dates,
        max_daily_basic_dates=args.max_daily_basic_dates,
        max_std_dates=args.max_std_dates,
    )


if __name__ == "__main__":
    main()