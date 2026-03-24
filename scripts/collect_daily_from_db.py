import sys
import time
import random
import pandas as pd
import akshare as ak
from common import get_conn, RAW_ROOT, log_job, normalize_trade_date, now_ts

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

def save_raw(df_raw, symbol, start_date, end_date, adjust):
    adjust_tag = adjust if adjust else "none"
    raw_dir = RAW_ROOT / "akshare" / "daily" / f"symbol={symbol}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / f"{start_date}_{end_date}_{adjust_tag}_{now_ts()}.csv"
    df_raw.to_csv(raw_file, index=False, encoding="utf-8-sig")
    return str(raw_file)

def fetch_with_retry(symbol, start_date, end_date, adjust="", max_retry=3):
    last_err = None
    for attempt in range(1, max_retry + 1):
        try:
            df_raw = ak.stock_zh_a_hist_tx(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                adjust=adjust
            )
            if df_raw is not None and not df_raw.empty:
                return df_raw, attempt, None
            last_err = "EMPTY"
        except Exception as e:
            last_err = str(e)

        sleep_s = 1.5 * attempt + random.uniform(0.5, 1.5)
        print(f"[RETRY] {symbol} attempt={attempt}/{max_retry} sleep={sleep_s:.1f}s err={last_err}")
        time.sleep(sleep_s)

    return None, max_retry, last_err

def main(start_date, end_date, limit=20, adjust=""):
    conn = get_conn()

    sql = """
    SELECT symbol, name
    FROM dim_symbol
    WHERE is_active = 1
      AND (symbol LIKE 'sh%' OR symbol LIKE 'sz%')
    ORDER BY symbol
    """
    if limit > 0:
        sql += f" LIMIT {limit}"

    symbols = pd.read_sql(sql, conn)

    total_rows = 0
    success_cnt = 0
    fail_cnt = 0

    fail_dir = RAW_ROOT / "akshare" / "failed_lists"
    fail_dir.mkdir(parents=True, exist_ok=True)
    fail_file = fail_dir / f"failed_{start_date}_{end_date}_{now_ts()}.csv"
    failed_rows = []

    print(f"本次计划采集股票数: {len(symbols)}")

    for _, item in symbols.iterrows():
        symbol = item["symbol"]
        name = item["name"]

        df_raw, used_retry, err = fetch_with_retry(symbol, start_date, end_date, adjust, max_retry=3)

        if df_raw is None or df_raw.empty:
            fail_cnt += 1
            failed_rows.append({"symbol": symbol, "name": name, "error": err})
            log_job(conn, "collect_daily_from_db", "ERROR", f"{symbol}: {err}")
            print(f"[ERROR] {symbol}: {err}")
            continue

        try:
            raw_file = save_raw(df_raw, symbol, start_date, end_date, adjust)

            df = df_raw.rename(columns={"date": "trade_date"})
            df["trade_date"] = df["trade_date"].apply(normalize_trade_date)
            df["symbol"] = symbol
            df["name"] = name
            df["adjust"] = adjust
            df["source"] = "akshare_stock_zh_a_hist_tx"

            need_cols = [
                "trade_date", "symbol", "name",
                "open", "high", "low", "close", "amount",
                "adjust", "source"
            ]
            df = df[need_cols]

            save_rows(conn, df)
            total_rows += len(df)
            success_cnt += 1

            log_job(conn, "collect_daily_from_db", "SUCCESS", f"{symbol} 写入 {len(df)} 行, retry={used_retry}, raw={raw_file}")
            print(f"[OK] {symbol} 写入 {len(df)} 行 retry={used_retry}")

            time.sleep(random.uniform(0.8, 1.8))

        except Exception as e:
            fail_cnt += 1
            failed_rows.append({"symbol": symbol, "name": name, "error": str(e)})
            log_job(conn, "collect_daily_from_db", "ERROR", f"{symbol}: {str(e)}")
            print(f"[ERROR] {symbol}: {e}")

    if failed_rows:
        pd.DataFrame(failed_rows).to_csv(fail_file, index=False, encoding="utf-8-sig")
        print(f"失败清单已保存: {fail_file}")

    conn.close()
    print(f"完成，总写入行数: {total_rows}, 成功股票数: {success_cnt}, 失败股票数: {fail_cnt}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python collect_daily_from_db.py 20250101 20250314 [limit] [adjust]")
        sys.exit(1)

    start_date = sys.argv[1]
    end_date = sys.argv[2]
    limit = int(sys.argv[3]) if len(sys.argv) >= 4 else 20
    adjust = sys.argv[4] if len(sys.argv) >= 5 else ""

    main(start_date, end_date, limit, adjust)