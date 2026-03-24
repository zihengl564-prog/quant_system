import os
import sys
import sqlite3
import tushare as ts
from dotenv import load_dotenv

load_dotenv(r"D:\quant_system\config\.env")

DB_PATH = os.getenv("DB_PATH", r"D:\quant_system\data\quant.db")
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "").strip()

def log_job(conn, job_name, status, message):
    conn.execute(
        "INSERT INTO etl_job_log (job_name, status, message) VALUES (?, ?, ?)",
        (job_name, status, message)
    )
    conn.commit()

def upsert_watermark(conn, job_name, last_value):
    conn.execute("""
    INSERT OR REPLACE INTO ops_watermark (job_name, last_value, updated_at)
    VALUES (?, ?, CURRENT_TIMESTAMP)
    """, (job_name, last_value))
    conn.commit()

def main(start_date, end_date):
    if not TUSHARE_TOKEN or "这里填你的真实token" in TUSHARE_TOKEN:
        print("请先在 D:\\quant_system\\config\\.env 中填写真实 TUSHARE_TOKEN")
        sys.exit(1)

    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()

    df = pro.trade_cal(
        exchange="SSE",
        start_date=start_date,
        end_date=end_date,
        fields="exchange,cal_date,is_open,pretrade_date"
    )

    if df is None or df.empty:
        print("未获取到交易日历数据")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)

    rows = []
    for _, row in df.iterrows():
        rows.append((
            row["cal_date"],
            row["exchange"],
            int(row["is_open"]),
            "tushare_trade_cal",
            row["pretrade_date"]
        ))

    conn.executemany("""
    INSERT OR REPLACE INTO dim_trade_calendar
    (cal_date, exchange, is_open, source, updated_at, pretrade_date)
    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
    """, rows)

    log_job(conn, "refresh_trade_calendar", "SUCCESS", f"{start_date}-{end_date} 写入 {len(rows)} 条")
    upsert_watermark(conn, "refresh_trade_calendar", end_date)

    conn.close()
    print(f"交易日历刷新完成，写入 {len(rows)} 条")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python refresh_trade_calendar.py 20240101 20261231")
        sys.exit(1)

    main(sys.argv[1], sys.argv[2])