from datetime import datetime

import pandas as pd

from src.common.logging_utils import get_app_logger, get_error_logger
from src.config.settings import settings
from src.data_access.raw_data_repository import RawDataRepository
from src.data_access.standardized_data_repository import StandardizedDataRepository


def _format_yyyymmdd_to_iso(date_value) -> str | None:
    if date_value is None:
        return None

    if pd.isna(date_value):
        return None

    s = str(date_value).strip()
    if not s:
        return None

    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"

    return s


class TradingCalendarBuilder:
    def __init__(self):
        self.raw_repo = RawDataRepository(settings.RAW_DB_PATH)
        self.std_repo = StandardizedDataRepository(settings.STD_DB_PATH)
        self.app_logger = get_app_logger()
        self.error_logger = get_error_logger()

    def build(self, exchange: str | None = None) -> int:
        exchange = exchange or settings.DEFAULT_EXCHANGE

        self.app_logger.info(
            f"[TradingCalendarBuilder] 开始构建 std_calendar, exchange={exchange}"
        )

        rows = self.raw_repo.fetch_all(
            """
            SELECT exchange, cal_date, is_open, pretrade_date
            FROM ods_trade_cal
            WHERE exchange = ?
            ORDER BY cal_date;
            """,
            (exchange,),
        )

        if not rows:
            self.app_logger.info("[TradingCalendarBuilder] ods_trade_cal 没有可用数据")
            return 0

        df = pd.DataFrame([dict(row) for row in rows])

        df["trade_date"] = df["cal_date"].map(_format_yyyymmdd_to_iso)
        df["prev_trade_date"] = df["pretrade_date"].map(_format_yyyymmdd_to_iso)
        df["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        output_df = df[
            ["trade_date", "exchange", "is_open", "prev_trade_date", "update_time"]
        ].copy()

        self.std_repo.upsert_dataframe(
            table_name="std_calendar",
            df=output_df,
            unique_keys=["trade_date"],
        )

        self.app_logger.info(
            f"[TradingCalendarBuilder] std_calendar 构建完成，写入/更新 {len(output_df)} 行"
        )
        return len(output_df)