import argparse
from datetime import datetime

import pandas as pd

from src.common.logging_utils import get_app_logger, get_error_logger
from src.config.settings import settings
from src.data_access.raw_data_repository import RawDataRepository
from src.datasources.tushare_provider import TushareProvider


class TradeCalendarIngestor:
    def __init__(self):
        self.provider = TushareProvider()
        self.repo = RawDataRepository(settings.RAW_DB_PATH)
        self.app_logger = get_app_logger()
        self.error_logger = get_error_logger()

    def backfill(
        self,
        start_date: str,
        end_date: str,
        exchange: str | None = None,
    ) -> int:
        exchange = exchange or settings.DEFAULT_EXCHANGE

        self.app_logger.info(
            f"[TradeCalendarIngestor] 开始回填 trade_cal, exchange={exchange}, "
            f"start_date={start_date}, end_date={end_date}"
        )

        df = self.provider.get_trade_calendar(
            exchange=exchange,
            start_date=start_date,
            end_date=end_date,
        )

        if df.empty:
            self.app_logger.info("[TradeCalendarIngestor] 未获取到任何 trade_cal 数据")
            return 0

        expected_columns = ["exchange", "cal_date", "is_open", "pretrade_date"]
        df = df[expected_columns].copy()

        df["is_open"] = df["is_open"].astype(int)
        df["ingest_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.repo.upsert_dataframe(
            table_name="ods_trade_cal",
            df=df,
            unique_keys=["exchange", "cal_date"],
        )

        self.app_logger.info(
            f"[TradeCalendarIngestor] trade_cal 回填完成，写入/更新 {len(df)} 行"
        )
        return len(df)


def main():
    parser = argparse.ArgumentParser(description="Trade Calendar Ingestor")
    parser.add_argument("--start", required=True, help="开始日期，例如 20240101")
    parser.add_argument("--end", required=True, help="结束日期，例如 20260331")
    parser.add_argument("--exchange", default=settings.DEFAULT_EXCHANGE, help="交易所，默认 SSE")
    args = parser.parse_args()

    ingestor = TradeCalendarIngestor()
    ingestor.backfill(
        start_date=args.start,
        end_date=args.end,
        exchange=args.exchange,
    )


if __name__ == "__main__":
    main()