import argparse
import sqlite3
from pathlib import Path

import pandas as pd

from src.config.settings import settings


def _yyyymmdd_to_iso(date_str: str) -> str:
    s = str(date_str)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def _iso_to_yyyymmdd(date_str: str) -> str:
    return str(date_str).replace("-", "")


class DataGapAuditPipeline:
    def __init__(self):
        self.raw_db_path = settings.RAW_DB_PATH
        self.std_db_path = settings.STD_DB_PATH
        self.project_root = Path(settings.PROJECT_ROOT)
        self.export_dir = self.project_root / "data" / "exports" / "coverage"
        self.export_dir.mkdir(parents=True, exist_ok=True)

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

    def run(self, start_date: str, end_date: str) -> str:
        trade_dates_iso = self._fetch_open_trade_dates(start_date, end_date)

        if not trade_dates_iso:
            raise ValueError("未在 std_calendar 中找到指定范围内的开放交易日，请先确认 std_calendar 已构建。")

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

                record["ready_for_std_build"] = int(
                    record["has_ods_daily"] == 1
                    and record["has_ods_daily_basic"] == 1
                    and record["has_ods_adj_factor"] == 1
                )

                record["full_pipeline_ready"] = int(
                    record["has_ods_daily"] == 1
                    and record["has_ods_daily_basic"] == 1
                    and record["has_ods_adj_factor"] == 1
                    and record["has_std_equity_daily"] == 1
                )

                missing_items = []
                if record["has_ods_daily"] == 0:
                    missing_items.append("ods_daily")
                if record["has_ods_daily_basic"] == 0:
                    missing_items.append("ods_daily_basic")
                if record["has_ods_adj_factor"] == 0:
                    missing_items.append("ods_adj_factor")
                if record["has_std_equity_daily"] == 0:
                    missing_items.append("std_equity_daily")

                record["missing_items"] = ",".join(missing_items)

                records.append(record)

        finally:
            raw_conn.close()
            std_conn.close()

        df = pd.DataFrame(records)

        output_path = self.export_dir / f"daily_gap_audit_{start_date}_{end_date}.csv"
        df.to_csv(output_path, index=False, encoding="utf-8-sig")

        total_days = len(df)
        ready_days = int(df["ready_for_std_build"].sum())
        full_pipeline_days = int(df["full_pipeline_ready"].sum())
        missing_daily_days = int((df["has_ods_daily"] == 0).sum())
        missing_daily_basic_days = int((df["has_ods_daily_basic"] == 0).sum())
        missing_adj_factor_days = int((df["has_ods_adj_factor"] == 0).sum())
        missing_std_days = int((df["has_std_equity_daily"] == 0).sum())

        print("=" * 80)
        print("数据缺口审计完成")
        print(f"日期范围: {start_date} ~ {end_date}")
        print(f"开放交易日数: {total_days}")
        print(f"已具备 std 构建条件的交易日数: {ready_days}")
        print(f"已完成全链路（含 std_equity_daily）的交易日数: {full_pipeline_days}")
        print("-" * 80)
        print(f"缺 ods_daily 的交易日数: {missing_daily_days}")
        print(f"缺 ods_daily_basic 的交易日数: {missing_daily_basic_days}")
        print(f"缺 ods_adj_factor 的交易日数: {missing_adj_factor_days}")
        print(f"缺 std_equity_daily 的交易日数: {missing_std_days}")
        print("-" * 80)

        if missing_daily_days > 0:
            dates = df.loc[df["has_ods_daily"] == 0, "trade_date_raw"].tolist()
            print("缺 ods_daily 的日期:", dates[:20])

        if missing_daily_basic_days > 0:
            dates = df.loc[df["has_ods_daily_basic"] == 0, "trade_date_raw"].tolist()
            print("缺 ods_daily_basic 的日期:", dates[:20])

        if missing_adj_factor_days > 0:
            dates = df.loc[df["has_ods_adj_factor"] == 0, "trade_date_raw"].tolist()
            print("缺 ods_adj_factor 的日期:", dates[:20])

        if missing_std_days > 0:
            dates = df.loc[df["has_std_equity_daily"] == 0, "trade_date_raw"].tolist()
            print("缺 std_equity_daily 的日期:", dates[:20])

        print("-" * 80)
        print(f"覆盖报告已导出到: {output_path}")
        print("=" * 80)

        return str(output_path)


def main():
    parser = argparse.ArgumentParser(description="Data Gap Audit Pipeline")
    parser.add_argument("--start", required=True, help="开始日期，例如 20240101")
    parser.add_argument("--end", required=True, help="结束日期，例如 20240131")
    args = parser.parse_args()

    pipeline = DataGapAuditPipeline()
    pipeline.run(start_date=args.start, end_date=args.end)


if __name__ == "__main__":
    main()