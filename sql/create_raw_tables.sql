PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ods_trade_cal (
    exchange TEXT NOT NULL,
    cal_date TEXT NOT NULL,
    is_open INTEGER,
    pretrade_date TEXT,
    ingest_time TEXT NOT NULL,
    PRIMARY KEY (exchange, cal_date)
);

CREATE TABLE IF NOT EXISTS ods_stock_basic (
    ts_code TEXT NOT NULL,
    symbol TEXT,
    name TEXT,
    area TEXT,
    industry TEXT,
    market TEXT,
    list_date TEXT,
    delist_date TEXT,
    is_hs TEXT,
    act_name TEXT,
    act_ent_type TEXT,
    list_status TEXT NOT NULL,
    ingest_time TEXT NOT NULL,
    PRIMARY KEY (ts_code, list_status)
);

CREATE TABLE IF NOT EXISTS ods_daily (
    ts_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    pre_close REAL,
    change REAL,
    pct_chg REAL,
    vol REAL,
    amount REAL,
    ingest_time TEXT NOT NULL,
    PRIMARY KEY (ts_code, trade_date)
);

CREATE TABLE IF NOT EXISTS ods_daily_basic (
    ts_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    close REAL,
    turnover_rate REAL,
    turnover_rate_f REAL,
    volume_ratio REAL,
    pe REAL,
    pe_ttm REAL,
    pb REAL,
    ps REAL,
    ps_ttm REAL,
    dv_ratio REAL,
    dv_ttm REAL,
    total_share REAL,
    float_share REAL,
    free_share REAL,
    total_mv REAL,
    circ_mv REAL,
    ingest_time TEXT NOT NULL,
    PRIMARY KEY (ts_code, trade_date)
);

CREATE TABLE IF NOT EXISTS ods_adj_factor (
    ts_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    adj_factor REAL,
    ingest_time TEXT NOT NULL,
    PRIMARY KEY (ts_code, trade_date)
);