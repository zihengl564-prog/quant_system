from __future__ import annotations

import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "standardized_data" / "research_data.db"

TABLES = [
    ("feature_panel_v1", "ux_feature_panel_v1_trade_date_ts_code", "idx_feature_panel_v1_date_code"),
    ("label_panel_v1", "ux_label_panel_v1_trade_date_ts_code", "idx_label_panel_v1_date_code"),
    ("model_panel_v1", "ux_model_panel_v1_trade_date_ts_code", "idx_model_panel_v1_date_code"),
]


def duplicate_key_group_count(conn: sqlite3.Connection, table_name: str) -> int:
    sql = f"""
    SELECT COUNT(*)
    FROM (
        SELECT trade_date, ts_code, COUNT(*) AS c
        FROM {table_name}
        GROUP BY trade_date, ts_code
        HAVING COUNT(*) > 1
    ) t
    """
    return conn.execute(sql).fetchone()[0]


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def main() -> None:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"db not found: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()

        for table_name, unique_index_name, old_plain_index_name in TABLES:
            print(f"\n=== {table_name} ===")

            if not table_exists(conn, table_name):
                print("table not found, skip")
                continue

            before_rows = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            before_dup_groups = duplicate_key_group_count(conn, table_name)

            print(f"before_rows={before_rows}")
            print(f"before_duplicate_key_groups={before_dup_groups}")

            if before_dup_groups > 0:
                delete_sql = f"""
                DELETE FROM {table_name}
                WHERE rowid NOT IN (
                    SELECT MIN(rowid)
                    FROM {table_name}
                    GROUP BY trade_date, ts_code
                )
                """
                cursor.execute(delete_sql)
                print(f"duplicate rows removed from {table_name}")

            cursor.execute(f"DROP INDEX IF EXISTS {old_plain_index_name}")
            cursor.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {unique_index_name} "
                f"ON {table_name}(trade_date, ts_code)"
            )

            after_rows = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            after_dup_groups = duplicate_key_group_count(conn, table_name)

            print(f"after_rows={after_rows}")
            print(f"after_duplicate_key_groups={after_dup_groups}")

            if after_dup_groups > 0:
                raise ValueError(f"{table_name} still has duplicate key groups after enforcement")

        conn.commit()
        print("\nresearch panel constraints enforcement completed")

    finally:
        conn.close()


if __name__ == "__main__":
    main()