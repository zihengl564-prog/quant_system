PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS std_calendar (
    trade_date TEXT NOT NULL PRIMARY KEY,
    exchange TEXT,
    is_open INTEGER,
    prev_trade_date TEXT,
    update_time TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS std_security_master (
    ts_code TEXT NOT NULL PRIMARY KEY,
    symbol TEXT,
    name TEXT,
    area TEXT,
    industry TEXT,
    market TEXT,
    list_date TEXT,
    delist_date TEXT,
    is_hs TEXT,
    list_status TEXT,
    is_active INTEGER,
    update_time TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS std_equity_daily (
    ts_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    pre_close REAL,
    vol REAL,
    amount REAL,
    adj_factor REAL,
    open_adj REAL,
    high_adj REAL,
    low_adj REAL,
    close_adj REAL,
    turnover_rate REAL,
    turnover_rate_f REAL,
    volume_ratio REAL,
    pe_ttm REAL,
    pb REAL,
    ps_ttm REAL,
    total_mv REAL,
    circ_mv REAL,
    industry TEXT,
    market TEXT,
    update_time TEXT NOT NULL,
    PRIMARY KEY (ts_code, trade_date)
);

CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name TEXT NOT NULL,
    job_stage TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL
);