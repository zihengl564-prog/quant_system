import os
import sqlite3
from dotenv import load_dotenv

load_dotenv(r"D:\quant_system\config\.env")
DB_PATH = os.getenv("DB_PATH", r"D:\quant_system\data\quant.db")

def add_column_if_missing(conn, table_name, column_name, column_type):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    cols = [row[1] for row in cur.fetchall()]
    if column_name not in cols:
        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
        conn.commit()
        print(f"[ADD COLUMN] {table_name}.{column_name}")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# 保底创建表
cur.execute("""
CREATE TABLE IF NOT EXISTS dim_symbol (
    symbol TEXT PRIMARY KEY,
    name TEXT,
    market TEXT,
    is_active INTEGER DEFAULT 1,
    source TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS dim_trade_calendar (
    cal_date TEXT PRIMARY KEY,
    exchange TEXT,
    is_open INTEGER,
    source TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""")

# dim_symbol 增量字段
add_column_if_missing(conn, "dim_symbol", "ts_code", "TEXT")
add_column_if_missing(conn, "dim_symbol", "exchange", "TEXT")
add_column_if_missing(conn, "dim_symbol", "industry", "TEXT")
add_column_if_missing(conn, "dim_symbol", "list_status", "TEXT")
add_column_if_missing(conn, "dim_symbol", "list_date", "TEXT")

# dim_trade_calendar 增量字段
add_column_if_missing(conn, "dim_trade_calendar", "pretrade_date", "TEXT")

# 索引
cur.execute("CREATE INDEX IF NOT EXISTS idx_dim_symbol_ts_code ON dim_symbol(ts_code)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_dim_symbol_is_active ON dim_symbol(is_active)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_trade_calendar_is_open ON dim_trade_calendar(is_open)")

conn.commit()
conn.close()

print(f"数据库三期结构升级完成: {DB_PATH}")