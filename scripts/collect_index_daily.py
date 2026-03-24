import sys
import pandas as pd
import akshare as ak
from common import get_conn, RAW_ROOT, log_job, normalize_trade_date, now_ts, PROJECT_ROOT

INDEX_FILE = PROJECT_ROOT / "config" / "indexes.csv"

def save_raw(df_raw, index_code, start_date, end_date):
    raw_dir = RAW_ROOT / "akshare" / "index_daily" / f"index_code={index_code}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / f"{start_date}_{end_date}_{now_ts()}.csv"
    df_raw.to_csv(raw_file, index=False, encoding="utf-8-sig")
    return str(raw_file)

def save_rows(conn, df):
    sql = """
    INSERT OR REPLACE INTO fact_index_daily
    (trade_date, index_code, index_name, open, high, low, close, volume, amount, source)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    rows = [
        (
            str(row["trade_date"]),
            row["index_code"],
            row["index_name"],
            float(row["open"]) if pd.notna(row["open"]) else None,
            float(row["high"]) if pd.notna(row["high"]) else None,
            float(row["low"]) if pd.notna(row["low"]) else None,
            float(row["close"]) if pd.notna(row["close"]) else None,
            float(row["volume"]) if pd.notna(row["volume"]) else None,
            float(row["amount"]) if pd.notna(row["amount"]) else None,
            row["source"]
        )
        for _, row in df.iterrows()
    ]
    conn.executemany(sql, rows)
    conn.commit()

def main(start_date, end_date):
    conn = get_conn()
    idx_df = pd.read_csv(INDEX_FILE, dtype={"index_code": str})

    total_rows = 0

    for _, item in idx_df.iterrows():
        index_code = str(item["index_code"]).strip().zfill(6)
        index_name = str(item["index_name"]).strip()

        try:
            df_raw = ak.index_zh_a_hist(
                symbol=index_code,
                period="daily",
                start_date=start_date,
                end_date=end_date
            )

            if df_raw is None or df_raw.empty:
                log_job(conn, "collect_index_daily", "EMPTY", f"{index_code} 无数据")
                print(f"[EMPTY] {index_code} 无数据")
                continue

            raw_file = save_raw(df_raw, index_code, start_date, end_date)

            df = df_raw.rename(columns={
                "日期": "trade_date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount"
            })

            need_map = ["trade_date", "open", "high", "low", "close", "volume", "amount"]
            missing_cols = [c for c in need_map if c not in df.columns]
            if missing_cols:
                log_job(conn, "collect_index_daily", "ERROR", f"{index_code} 缺少字段: {missing_cols}")
                print(f"[ERROR] {index_code} 缺少字段: {missing_cols}")
                continue

            df["trade_date"] = df["trade_date"].apply(normalize_trade_date)
            df["index_code"] = index_code
            df["index_name"] = index_name
            df["source"] = "akshare_index_zh_a_hist"

            need_cols = [
                "trade_date", "index_code", "index_name",
                "open", "high", "low", "close", "volume", "amount", "source"
            ]
            df = df[need_cols]

            save_rows(conn, df)
            total_rows += len(df)

            log_job(conn, "collect_index_daily", "SUCCESS", f"{index_code} 写入 {len(df)} 行, raw={raw_file}")
            print(f"[OK] {index_code} 写入 {len(df)} 行")

        except Exception as e:
            log_job(conn, "collect_index_daily", "ERROR", f"{index_code}: {str(e)}")
            print(f"[ERROR] {index_code}: {e}")

    conn.close()
    print(f"完成，总写入行数: {total_rows}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python collect_index_daily.py 20250101 20250314")
        sys.exit(1)

    main(sys.argv[1], sys.argv[2])