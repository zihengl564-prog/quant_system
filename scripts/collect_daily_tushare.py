import sys
import time
import random
import pandas as pd
import tushare as ts
from common import get_conn, RAW_ROOT, TUSHARE_TOKEN, log_job, normalize_trade_date, now_ts

def save_raw(df_raw, ts_code, start_date, end_date):
    raw_dir = RAW_ROOT / "tushare" / "daily" / f"ts_code={ts_code}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / f"{start_date}_{end_date}_{now_ts()}.csv"
    df_raw.to_csv(raw_file, index=False, encoding="utf-8-sig")
    return str(raw_file)

def save_rows(conn, df):
    sql = """
    INSERT OR REPLACE INTO fact_price_daily_ts
    (trade_date, ts_code, symbol, name, open, high, low, close, pre_close, change, pct_chg, vol, amount, source)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    rows = [
        (
            str(row["trade_date"]),
            row["ts_code"],
            row["symbol"],
            row["name"],
            float(row["open"]) if pd.notna(row["open"]) else None,
            float(row["high"]) if pd.notna(row["high"]) else None,
            float(row["low"]) if pd.notna(row["low"]) else None,
            float(row["close"]) if pd.notna(row["close"]) else None,
            float(row["pre_close"]) if pd.notna(row["pre_close"]) else None,
            float(row["change"]) if pd.notna(row["change"]) else None,
            float(row["pct_chg"]) if pd.notna(row["pct_chg"]) else None,
            float(row["vol"]) if pd.notna(row["vol"]) else None,
            float(row["amount"]) if pd.notna(row["amount"]) else None,
            row["source"]
        )
        for _, row in df.iterrows()
    ]
    conn.executemany(sql, rows)
    conn.commit()

def main(start_date, end_date, limit=20):
    if not TUSHARE_TOKEN or "这里填你的真实token" in TUSHARE_TOKEN:
        print("请先在 .env 中填写真实 TUSHARE_TOKEN")
        sys.exit(1)

    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()

    conn = get_conn()

    sql = """
    SELECT ts_code, symbol, name
    FROM dim_symbol
    WHERE is_active = 1
      AND ts_code IS NOT NULL
    ORDER BY ts_code
    """
    if limit > 0:
        sql += f" LIMIT {limit}"

    symbols = pd.read_sql(sql, conn)
    print(f"本次计划采集 Tushare 日线股票数: {len(symbols)}")

    total_rows = 0
    success_cnt = 0
    fail_cnt = 0

    for _, item in symbols.iterrows():
        ts_code = item["ts_code"]
        symbol = item["symbol"]
        name = item["name"]

        try:
            df_raw = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)

            if df_raw is None or df_raw.empty:
                log_job(conn, "collect_daily_tushare", "EMPTY", f"{ts_code} 无数据")
                print(f"[EMPTY] {ts_code} 无数据")
                continue

            raw_file = save_raw(df_raw, ts_code, start_date, end_date)

            df = df_raw.copy()
            df["trade_date"] = df["trade_date"].apply(normalize_trade_date)
            df["symbol"] = symbol
            df["name"] = name
            df["source"] = "tushare_daily"

            need_cols = [
                "trade_date", "ts_code", "symbol", "name",
                "open", "high", "low", "close",
                "pre_close", "change", "pct_chg", "vol", "amount", "source"
            ]
            df = df[need_cols]

            save_rows(conn, df)
            total_rows += len(df)
            success_cnt += 1

            log_job(conn, "collect_daily_tushare", "SUCCESS", f"{ts_code} 写入 {len(df)} 行, raw={raw_file}")
            print(f"[OK] {ts_code} 写入 {len(df)} 行")

            time.sleep(random.uniform(0.2, 0.6))

        except Exception as e:
            fail_cnt += 1
            log_job(conn, "collect_daily_tushare", "ERROR", f"{ts_code}: {str(e)}")
            print(f"[ERROR] {ts_code}: {e}")
            time.sleep(random.uniform(0.8, 1.5))

    conn.close()
    print(f"完成，总写入行数: {total_rows}, 成功股票数: {success_cnt}, 失败股票数: {fail_cnt}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python collect_daily_tushare.py 20250101 20250314 [limit]")
        sys.exit(1)

    start_date = sys.argv[1]
    end_date = sys.argv[2]
    limit = int(sys.argv[3]) if len(sys.argv) >= 4 else 20

    main(start_date, end_date, limit)