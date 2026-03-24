CREATE INDEX IF NOT EXISTS idx_std_equity_daily_trade_date
ON std_equity_daily (trade_date);

CREATE INDEX IF NOT EXISTS idx_std_equity_daily_industry
ON std_equity_daily (industry);