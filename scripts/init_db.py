import os
import sqlite3
from dotenv import load_dotenv

# 读取配置
load_dotenv(r"D:\quant_system\config\.env")
DB_PATH = os.getenv("DB_PATH", r"D:\quant_system\data\quant.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# 日线行情表
cur.execute("""
CREATE TABLE IF NOT EXISTS fact_price_daily (
    trade_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    amount REAL,
    adjust TEXT,
    source TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (trade_date, symbol, adjust)
)
""")

# ETL 日志表
cur.execute("""
CREATE TABLE IF NOT EXISTS etl_job_log (
    job_name TEXT,
    run_time TEXT DEFAULT CURRENT_TIMESTAMP,
    status TEXT,
    message TEXT
)
""")

conn.commit()
conn.close()
print(f"数据库初始化完成: {DB_PATH}")