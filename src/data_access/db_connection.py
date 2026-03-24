import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from src.common.path_utils import ensure_parent_dir


class SQLiteConnectionManager:
    def __init__(self, db_path: str):
        self.db_path = str(Path(db_path))

    def ensure_db_file(self) -> None:
        ensure_parent_dir(self.db_path)
        Path(self.db_path).touch(exist_ok=True)

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        self.ensure_db_file()
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute_script(self, sql_script: str) -> None:
        with self.get_connection() as conn:
            conn.executescript(sql_script)

    def execute(
        self,
        sql: str,
        params: Optional[tuple] = None,
    ) -> None:
        with self.get_connection() as conn:
            if params is None:
                conn.execute(sql)
            else:
                conn.execute(sql, params)

    def executemany(
        self,
        sql: str,
        params_list: list[tuple],
    ) -> None:
        with self.get_connection() as conn:
            conn.executemany(sql, params_list)

    def fetch_all(
        self,
        sql: str,
        params: Optional[tuple] = None,
    ) -> list[sqlite3.Row]:
        with self.get_connection() as conn:
            cur = conn.execute(sql, params or ())
            return cur.fetchall()

    def fetch_one(
        self,
        sql: str,
        params: Optional[tuple] = None,
    ) -> Optional[sqlite3.Row]:
        with self.get_connection() as conn:
            cur = conn.execute(sql, params or ())
            return cur.fetchone()