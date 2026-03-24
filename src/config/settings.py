import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"

load_dotenv(ENV_PATH)


class Settings:
    PROJECT_ROOT = PROJECT_ROOT

    TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "").strip()

    RAW_DB_PATH = os.getenv(
        "RAW_DB_PATH",
        str(PROJECT_ROOT / "data" / "raw_data" / "raw_market_data.db"),
    )
    STD_DB_PATH = os.getenv(
        "STD_DB_PATH",
        str(PROJECT_ROOT / "data" / "standardized_data" / "research_data.db"),
    )

    APP_LOG_PATH = os.getenv(
        "APP_LOG_PATH",
        str(PROJECT_ROOT / "logs" / "application.log"),
    )
    JOB_LOG_PATH = os.getenv(
        "JOB_LOG_PATH",
        str(PROJECT_ROOT / "logs" / "job_runs.log"),
    )
    ERROR_LOG_PATH = os.getenv(
        "ERROR_LOG_PATH",
        str(PROJECT_ROOT / "logs" / "errors.log"),
    )

    DEFAULT_START_DATE = os.getenv("DEFAULT_START_DATE", "20100101")
    DEFAULT_END_DATE = os.getenv("DEFAULT_END_DATE", "20261231")
    DEFAULT_EXCHANGE = os.getenv("DEFAULT_EXCHANGE", "SSE")


settings = Settings()