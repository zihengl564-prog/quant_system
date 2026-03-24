import os
import sys
import sqlite3
import pandas as pd
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

def ts_to_ak_symbol(ts_code: str) -> str:
    # 000001.SZ -> sz000001
    code, exch = ts_code.split(".")
    return exch.lower() + code

def main():
    if not TUSHARE_TOKEN or "这里填你的真实token" in TUSHARE_TOKEN:
        print("请先在 D:\\quant_system\\config\\.env 中填写真实 TUSHARE_TOKEN")
        sys.exit(1)

    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()

    frames = []
    for status in ["L", "P", "D"]:
        df = pro.stock_basic(
            exchange="",
            list_status=status,
            fields="ts_code,symbol,name,industry,market,exchange,list_status,list_date"
        )
        if df is not None and not df.empty:
            frames.append(df)

    if not frames:
        print("未从 Tushare 获取到股票池数据")
        sys.exit(1)

    all_df = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["ts_code"])
    all_df["symbol_ak"] = all_df["ts_code"].apply(ts_to_ak_symbol)
    all_df["is_active"] = all_df["list_status"].apply(lambda x: 1 if x == "L" else 0)
    all_df["source"] = "tushare_stock_basic"

    conn = sqlite3.connect(DB_PATH)

    rows = []
    for _, row in all_df.iterrows():
        rows.append((
            row["symbol_ak"],
            row["name"],
            row["market"],
            int(row["is_active"]),
            row["source"],
            row["ts_code"],
            row["exchange"],
            row["industry"],
            row["list_status"],
            row["list_date"]
        ))

    conn.executemany("""
    INSERT OR REPLACE INTO dim_symbol
    (symbol, name, market, is_active, source, updated_at, ts_code, exchange, industry, list_status, list_date)
    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?)
    """, rows)

    log_job(conn, "refresh_symbol_universe", "SUCCESS", f"写入 {len(rows)} 条")
    upsert_watermark(conn, "refresh_symbol_universe", str(len(rows)))

    conn.close()
    print(f"股票池刷新完成，写入 {len(rows)} 条")

if __name__ == "__main__":
    main()