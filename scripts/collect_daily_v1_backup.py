import os
import sys
import sqlite3
import pandas as pd
import akshare as ak
from dotenv import load_dotenv

load_dotenv(r"D:\quant_system\config\.env")
DB_PATH = os.getenv("DB_PATH", r"D:\quant_system\data\quant.db")
SYMBOL_FILE = r"D:\quant_system\data\symbols.csv"

def log_job(conn, job_name, status, message):
    conn.execute(
        "INSERT INTO etl_job_log (job_name, status, message) VALUES (?, ?, ?)",
        (job_name, status, message)
    )
    conn.commit()

def save_rows(conn, df):
    sql = """
    INSERT OR REPLACE INTO fact_price_daily
    (trade_date, symbol, name, open, high, low, close, amount, adjust, source)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    rows = [
        (
            str(row["trade_date"]),
            row["symbol"],
            row["name"],
            float(row["open"]) if pd.notna(row["open"]) else None,
            float(row["high"]) if pd.notna(row["high"]) else None,
            float(row["low"]) if pd.notna(row["low"]) else None,
            float(row["close"]) if pd.notna(row["close"]) else None,
            float(row["amount"]) if pd.notna(row["amount"]) else None,
            row["adjust"],
            row["source"]
        )
        for _, row in df.iterrows()
    ]
    conn.executemany(sql, rows)
    conn.commit()

def main(start_date, end_date, adjust=""):
    conn = sqlite3.connect(DB_PATH)
    symbols = pd.read_csv(SYMBOL_FILE)
    total_rows = 0

    for _, item in symbols.iterrows():
        symbol = item["symbol"]
        name = item["name"]

        try:
            df = ak.stock_zh_a_hist_tx(symbol=symbol, start_date=start_date, end_date=end_date, adjust=adjust)
            if df is None or df.empty:
                log_job(conn, "collect_daily", "EMPTY", f"{symbol} 无数据")
                continue

            df = df.rename(columns={"date":"trade_date"})
            df["symbol"] = symbol
            df["name"] = name
            df["adjust"] = adjust
            df["source"] = "akshare_stock_zh_a_hist_tx"

            need_cols = ["trade_date","symbol","name","open","high","low","close","amount","adjust","source"]
            df = df[need_cols]

            save_rows(conn, df)
            total_rows += len(df)
            log_job(conn, "collect_daily", "SUCCESS", f"{symbol} 写入 {len(df)} 行")
            print(f"[OK] {symbol} 写入 {len(df)} 行")
        except Exception as e:
            log_job(conn, "collect_daily", "ERROR", f"{symbol}: {str(e)}")
            print(f"[ERROR] {symbol}: {e}")

    conn.close()
    print(f"完成，总写入行数: {total_rows}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python collect_daily.py 20250101 20250314")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])