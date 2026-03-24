CREATE INDEX IF NOT EXISTS idx_ods_daily_trade_date
ON ods_daily (trade_date);

CREATE INDEX IF NOT EXISTS idx_ods_daily_basic_trade_date
ON ods_daily_basic (trade_date);

CREATE INDEX IF NOT EXISTS idx_ods_adj_factor_trade_date
ON ods_adj_factor (trade_date);