from common import (
    ENV_PATH, PROJECT_ROOT, DB_PATH, RAW_ROOT, LOG_DIR, INCOMING_NEWS_DIR,
    TUSHARE_TOKEN, get_conn, assert_writable, check_required_tables
)

def main():
    print("开始运行环境自检...")

    if not ENV_PATH.exists():
        raise RuntimeError(f".env 不存在: {ENV_PATH}")

    if not PROJECT_ROOT.exists():
        raise RuntimeError(f"PROJECT_ROOT 不存在: {PROJECT_ROOT}")

    assert_writable(DB_PATH.parent)
    assert_writable(RAW_ROOT)
    assert_writable(LOG_DIR)
    assert_writable(INCOMING_NEWS_DIR)

    conn = get_conn()
    check_required_tables(conn, [
        "etl_job_log",
        "dim_symbol",
        "dim_trade_calendar",
        "fact_price_daily",
        "fact_price_daily_ts",
        "fact_index_daily",
        "ops_watermark"
    ])
    conn.close()

    if not TUSHARE_TOKEN or "这里填你的真实token" in TUSHARE_TOKEN:
        raise RuntimeError("TUSHARE_TOKEN 未正确配置")

    print("自检通过：环境、目录、数据库、关键表、Token 均正常")

if __name__ == "__main__":
    main()