import os
import sqlite3
import pandas as pd
from dotenv import load_dotenv

load_dotenv(r"D:\quant_system\config\.env")
DB_PATH = os.getenv("DB_PATH", r"D:\quant_system\data\quant.db")
SYMBOL_FILE = r"D:\quant_system\data\symbols.csv"

def infer_market(symbol: str) -> str:
    if str(symbol).startswith("sh"):
        return "SH"
    if str(symbol).startswith("sz"):
        return "SZ"
    if str(symbol).startswith("bj"):
        return "BJ"
    return "UNKNOWN"

conn = sqlite3.connect(DB_PATH)
df = pd.read_csv(SYMBOL_FILE)

rows = []
for _, row in df.iterrows():
    symbol = str(row["symbol"]).strip()
    name = str(row["name"]).strip()
    market = infer_market(symbol)
    rows.append((symbol, name, market, 1, "symbols_csv"))

conn.executemany("""
INSERT OR REPLACE INTO dim_symbol
(symbol, name, market, is_active, source, updated_at)
VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
""", rows)

conn.commit()
conn.close()

print(f"dim_symbol 已写入 {len(rows)} 条")