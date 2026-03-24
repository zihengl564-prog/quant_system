import os
import sys
import json
import hashlib
import shutil
import sqlite3
from dotenv import load_dotenv

load_dotenv(r"D:\quant_system\config\.env")

DB_PATH = os.getenv("DB_PATH", r"D:\quant_system\data\quant.db")
RAW_ROOT = os.getenv("RAW_ROOT", r"D:\quant_system\data\raw")

def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()

def main(file_path: str):
    if not os.path.exists(file_path):
        print(f"文件不存在: {file_path}")
        sys.exit(1)

    raw_news_dir = os.path.join(RAW_ROOT, "news")
    os.makedirs(raw_news_dir, exist_ok=True)

    base_name = os.path.basename(file_path)
    archived_path = os.path.join(raw_news_dir, base_name)
    shutil.copy2(file_path, archived_path)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    count = 0
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            item = json.loads(line)
            source = item.get("source", "")
            pub_time = item.get("pub_time", "")
            title = item.get("title", "")
            content = item.get("content", "")
            symbol = item.get("symbol", "")

            content_hash = sha1_text(title + "||" + content)
            news_id = sha1_text(source + "||" + pub_time + "||" + title)

            cur.execute("""
            INSERT OR REPLACE INTO fact_news_raw
            (news_id, source, pub_time, title, content, symbol, content_hash, raw_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                news_id, source, pub_time, title, content, symbol, content_hash, archived_path
            ))
            count += 1

    cur.execute("""
    INSERT INTO etl_job_log (job_name, status, message)
    VALUES (?, ?, ?)
    """, ("ingest_news_jsonl", "SUCCESS", f"{file_path} 导入 {count} 条"))
    conn.commit()
    conn.close()

    print(f"导入完成: {count} 条")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python ingest_news_jsonl.py D:\\quant_system\\data\\incoming\\news\\news_sample.jsonl")
        sys.exit(1)

    main(sys.argv[1])