from __future__ import annotations

import pandas as pd

from src.data_access.db_connection import SQLiteConnectionManager


class StandardizedDataRepository:
    def __init__(self, db_path: str):
        self.db = SQLiteConnectionManager(db_path)

    def execute_script(self, sql_script: str) -> None:
        self.db.execute_script(sql_script)

    def fetch_all(self, sql: str, params: tuple | None = None):
        return self.db.fetch_all(sql, params)

    def insert_dataframe(
        self,
        table_name: str,
        df: pd.DataFrame,
        if_exists: str = "append",
    ) -> None:
        if df.empty:
            return

        with self.db.get_connection() as conn:
            df.to_sql(
                name=table_name,
                con=conn,
                if_exists=if_exists,
                index=False,
            )

    def upsert_dataframe(
        self,
        table_name: str,
        df: pd.DataFrame,
        unique_keys: list[str],
    ) -> None:
        if df.empty:
            return

        records = df.to_dict(orient="records")
        columns = list(df.columns)

        insert_columns = ", ".join(columns)
        placeholders = ", ".join(["?"] * len(columns))

        update_columns = [c for c in columns if c not in unique_keys]
        update_clause = ", ".join([f"{c}=excluded.{c}" for c in update_columns])

        sql = f"""
        INSERT INTO {table_name} ({insert_columns})
        VALUES ({placeholders})
        ON CONFLICT({", ".join(unique_keys)}) DO UPDATE SET
        {update_clause};
        """

        params_list = [tuple(record.get(col) for col in columns) for record in records]
        self.db.executemany(sql, params_list)