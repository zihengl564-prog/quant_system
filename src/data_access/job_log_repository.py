from __future__ import annotations

from datetime import datetime

from src.data_access.db_connection import SQLiteConnectionManager


class JobLogRepository:
    def __init__(self, db_path: str):
        self.db = SQLiteConnectionManager(db_path)

    def log_job_run(
        self,
        job_name: str,
        job_stage: str,
        status: str,
        message: str = "",
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        sql = """
        INSERT INTO job_runs (
            job_name,
            job_stage,
            status,
            message,
            started_at,
            finished_at
        )
        VALUES (?, ?, ?, ?, ?, ?);
        """
        params = (
            job_name,
            job_stage,
            status,
            message,
            started_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            finished_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        self.db.execute(sql, params)

    def fetch_recent_runs(self, limit: int = 20):
        sql = f"""
        SELECT *
        FROM job_runs
        ORDER BY id DESC
        LIMIT {limit};
        """
        return self.db.fetch_all(sql)