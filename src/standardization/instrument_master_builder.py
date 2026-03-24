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


class InstrumentMasterBuilder:
    def __init__(self):
        self.raw_repo = RawDataRepository(settings.RAW_DB_PATH)
        self.std_repo = StandardizedDataRepository(settings.STD_DB_PATH)
        self.app_logger = get_app_logger()
        self.error_logger = get_error_logger()

    def build(self) -> int:
        self.app_logger.info("[InstrumentMasterBuilder] 开始构建 std_security_master")

        rows = self.raw_repo.fetch_all(
            """
            SELECT
                ts_code,
                symbol,
                name,
                area,
                industry,
                market,
                list_date,
                delist_date,
                is_hs,
                list_status
            FROM ods_stock_basic
            ORDER BY ts_code, list_status;
            """
        )

        if not rows:
            self.app_logger.warning("[InstrumentMasterBuilder] ods_stock_basic 没有可用数据")
            return 0

        df = pd.DataFrame([dict(row) for row in rows])

        status_priority_map = {"L": 0, "P": 1, "D": 2}
        df["status_priority"] = df["list_status"].map(status_priority_map).fillna(9)

        df = df.sort_values(["ts_code", "status_priority"]).copy()
        df = df.drop_duplicates(subset=["ts_code"], keep="first").copy()

        df["list_date"] = df["list_date"].map(_format_yyyymmdd_to_iso)
        df["delist_date"] = df["delist_date"].map(_format_yyyymmdd_to_iso)

        df["is_active"] = (
            (df["list_status"] == "L")
            & (df["delist_date"].isna() | (df["delist_date"] == ""))
        ).astype(int)

        df["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        output_df = df[
            [
                "ts_code",
                "symbol",
                "name",
                "area",
                "industry",
                "market",
                "list_date",
                "delist_date",
                "is_hs",
                "list_status",
                "is_active",
                "update_time",
            ]
        ].copy()

        self.std_repo.upsert_dataframe(
            table_name="std_security_master",
            df=output_df,
            unique_keys=["ts_code"],
        )

        self.app_logger.info(
            f"[InstrumentMasterBuilder] std_security_master 构建完成，写入/更新 {len(output_df)} 行"
        )
        return len(output_df)