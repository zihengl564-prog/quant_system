from datetime import datetime

from src.common.logging_utils import get_app_logger, get_error_logger
from src.config.settings import settings
from src.data_access.raw_data_repository import RawDataRepository
from src.datasources.tushare_provider import TusharePermissionError, TushareProvider


class StockMasterIngestor:
    def __init__(self):
        self.provider = TushareProvider()
        self.repo = RawDataRepository(settings.RAW_DB_PATH)
        self.app_logger = get_app_logger()
        self.error_logger = get_error_logger()

    def backfill(
        self,
        exchanges: list[str] | None = None,
        list_statuses: list[str] | None = None,
    ) -> dict:
        exchanges = exchanges or ["SSE", "SZSE", "BSE"]
        list_statuses = list_statuses or ["L", "D", "P"]

        self.app_logger.info(
            f"[StockMasterIngestor] 开始回填 stock_basic, exchanges={exchanges}, "
            f"list_statuses={list_statuses}"
        )

        total_rows = 0
        success_slices: list[dict] = []
        empty_slices: list[dict] = []
        failed_slices: list[dict] = []

        for exchange in exchanges:
            for list_status in list_statuses:
                self.app_logger.info(
                    f"[StockMasterIngestor] 拉取 stock_basic, exchange={exchange}, list_status={list_status}"
                )

                try:
                    df = self.provider.get_stock_basic(
                        exchange=exchange,
                        list_status=list_status,
                    )

                    if df.empty:
                        self.app_logger.warning(
                            f"[StockMasterIngestor] stock_basic 无数据, exchange={exchange}, list_status={list_status}"
                        )
                        empty_slices.append(
                            {
                                "exchange": exchange,
                                "list_status": list_status,
                                "rows": 0,
                            }
                        )
                        continue

                    expected_columns = [
                        "ts_code",
                        "symbol",
                        "name",
                        "area",
                        "industry",
                        "market",
                        "list_date",
                        "delist_date",
                        "is_hs",
                        "act_name",
                        "act_ent_type",
                        "list_status",
                    ]

                    for col in expected_columns:
                        if col not in df.columns:
                            df[col] = None

                    df = df[expected_columns].copy()
                    df["ingest_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    self.repo.upsert_dataframe(
                        table_name="ods_stock_basic",
                        df=df,
                        unique_keys=["ts_code", "list_status"],
                    )

                    row_count = len(df)
                    total_rows += row_count

                    success_slices.append(
                        {
                            "exchange": exchange,
                            "list_status": list_status,
                            "rows": row_count,
                        }
                    )

                    self.app_logger.info(
                        f"[StockMasterIngestor] stock_basic 回填完成, "
                        f"exchange={exchange}, list_status={list_status}, 写入/更新 {row_count} 行"
                    )

                except TusharePermissionError as e:
                    failed_info = {
                        "exchange": exchange,
                        "list_status": list_status,
                        "error_type": type(e).__name__,
                        "error_code": e.code,
                        "error_message": str(e),
                    }
                    failed_slices.append(failed_info)
                    self.error_logger.error(
                        f"[StockMasterIngestor] stock_basic 权限不可用，终止该接口回填: "
                        f"exchange={exchange}, list_status={list_status}, "
                        f"code={e.code}, msg={e.message}"
                    )
                    raise

                except Exception as e:
                    failed_info = {
                        "exchange": exchange,
                        "list_status": list_status,
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    }
                    failed_slices.append(failed_info)

                    self.error_logger.exception(
                        f"[StockMasterIngestor] stock_basic 分片失败, "
                        f"exchange={exchange}, list_status={list_status}, "
                        f"error={type(e).__name__}: {e}"
                    )
                    continue

        self.app_logger.info(
            f"[StockMasterIngestor] stock_basic 回填结束, total_rows={total_rows}, "
            f"success_slices={len(success_slices)}, empty_slices={len(empty_slices)}, "
            f"failed_slices={len(failed_slices)}"
        )

        return {
            "total_rows": total_rows,
            "success_slices": success_slices,
            "empty_slices": empty_slices,
            "failed_slices": failed_slices,
        }
