from common import get_conn

conn = get_conn()
cur = conn.cursor()

# -----------------------------
# 1) 修复 fact_price_daily
# -----------------------------
cur.execute("""
CREATE TABLE IF NOT EXISTS fact_price_daily_new (
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

# 用 INSERT OR REPLACE + 规范化日期，自动去重
# ORDER BY created_at ASC: 较新的记录后写入，冲突时覆盖旧记录
cur.execute("""
INSERT OR REPLACE INTO fact_price_daily_new
(trade_date, symbol, name, open, high, low, close, amount, adjust, source, created_at)
SELECT
    REPLACE(trade_date, '-', '') AS trade_date,
    symbol,
    name,
    open,
    high,
    low,
    close,
    amount,
    adjust,
    source,
    created_at
FROM fact_price_daily
ORDER BY created_at ASC
""")

# 备份旧表
cur.execute("DROP TABLE IF EXISTS fact_price_daily_old")
cur.execute("ALTER TABLE fact_price_daily RENAME TO fact_price_daily_old")
cur.execute("ALTER TABLE fact_price_daily_new RENAME TO fact_price_daily")

# 重建索引
cur.execute("CREATE INDEX IF NOT EXISTS idx_price_daily_symbol ON fact_price_daily(symbol)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_price_daily_trade_date ON fact_price_daily(trade_date)")

# -----------------------------
# 2) 修复 fact_index_daily
# -----------------------------
cur.execute("""
CREATE TABLE IF NOT EXISTS fact_index_daily_new (
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

cur.execute("""
INSERT OR REPLACE INTO fact_index_daily_new
(trade_date, index_code, index_name, open, high, low, close, volume, amount, source, created_at)
SELECT
    REPLACE(trade_date, '-', '') AS trade_date,
    index_code,
    index_name,
    open,
    high,
    low,
    close,
    volume,
    amount,
    source,
    created_at
FROM fact_index_daily
ORDER BY created_at ASC
""")

cur.execute("DROP TABLE IF EXISTS fact_index_daily_old")
cur.execute("ALTER TABLE fact_index_daily RENAME TO fact_index_daily_old")
cur.execute("ALTER TABLE fact_index_daily_new RENAME TO fact_index_daily")

cur.execute("CREATE INDEX IF NOT EXISTS idx_index_daily_code ON fact_index_daily(index_code)")

conn.commit()
conn.close()

print("日期迁移完成：fact_price_daily / fact_index_daily 已统一为 YYYYMMDD，重复键已自动去重")