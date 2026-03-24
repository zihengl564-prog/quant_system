import os
import sqlite3
from dotenv import load_dotenv

load_dotenv(r"D:\quant_system\config\.env")
DB_PATH = os.getenv("DB_PATH", r"D:\quant_system\data\quant.db")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS fact_price_daily_ts (
    trade_date TEXT NOT NULL,
    ts_code TEXT NOT NULL,
    symbol TEXT,
    name TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    pre_close REAL,
    change REAL,
    pct_chg REAL,
    vol REAL,
    amount REAL,
    source TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (trade_date, ts_code)
)
""")

cur.execute("CREATE INDEX IF NOT EXISTS idx_price_daily_ts_code ON fact_price_daily_ts(ts_code)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_price_daily_ts_trade_date ON fact_price_daily_ts(trade_date)")

conn.commit()
conn.close()

print(f"数据库四期结构升级完成: {DB_PATH}")