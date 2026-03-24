import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.config.settings import settings


def _build_logger(name: str, log_file: str, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    if logger.handlers:
        return logger

    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    )

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


def get_app_logger() -> logging.Logger:
    return _build_logger("app_logger", settings.APP_LOG_PATH, logging.INFO)


def get_job_logger() -> logging.Logger:
    return _build_logger("job_logger", settings.JOB_LOG_PATH, logging.INFO)


def get_error_logger() -> logging.Logger:
    return _build_logger("error_logger", settings.ERROR_LOG_PATH, logging.ERROR)