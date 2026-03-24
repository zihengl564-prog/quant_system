import os
import sqlite3
from dotenv import load_dotenv

load_dotenv(r"D:\quant_system\config\.env")
DB_PATH = os.getenv("DB_PATH", r"D:\quant_system\data\quant.db")
RAW_ROOT = os.getenv("RAW_ROOT", r"D:\quant_system\data\raw")

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(RAW_ROOT, exist_ok=True)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# 你已有的表，保留
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

cur.execute("""
CREATE TABLE IF NOT EXISTS etl_job_log (
    job_name TEXT,
    run_time TEXT DEFAULT CURRENT_TIMESTAMP,
    status TEXT,
    message TEXT
)
""")

# 股票维表
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

# 交易日历表（先建空表，后续接 Tushare）
cur.execute("""
CREATE TABLE IF NOT EXISTS dim_trade_calendar (
    cal_date TEXT PRIMARY KEY,
    exchange TEXT,
    is_open INTEGER,
    source TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""")

# 指数日线
cur.execute("""
CREATE TABLE IF NOT EXISTS fact_index_daily (
    trade_date TEXT NOT NULL,
    index_code TEXT NOT NULL,
    index_name TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    amount REAL,
    source TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (trade_date, index_code)
)
""")

# 新闻原始表
cur.execute("""
CREATE TABLE IF NOT EXISTS fact_news_raw (
    news_id TEXT PRIMARY KEY,
    source TEXT,
    pub_time TEXT,
    title TEXT,
    content TEXT,
    symbol TEXT,
    content_hash TEXT,
    raw_path TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""")

# 游标 / 水位
cur.execute("""
CREATE TABLE IF NOT EXISTS ops_watermark (
    job_name TEXT PRIMARY KEY,
    last_value TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""")

# 数据质量检查结果
cur.execute("""
CREATE TABLE IF NOT EXISTS ops_data_quality (
    check_name TEXT,
    check_time TEXT DEFAULT CURRENT_TIMESTAMP,
    status TEXT,
    detail TEXT
)
""")

cur.execute("CREATE INDEX IF NOT EXISTS idx_price_daily_symbol ON fact_price_daily(symbol)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_price_daily_trade_date ON fact_price_daily(trade_date)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_index_daily_code ON fact_index_daily(index_code)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_news_pub_time ON fact_news_raw(pub_time)")

conn.commit()
conn.close()

print(f"数据库二期初始化完成: {DB_PATH}")