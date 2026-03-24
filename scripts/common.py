import os
import sqlite3
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BASE_DIR / "config" / ".env"

load_dotenv(ENV_PATH)

PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", str(BASE_DIR)))
DB_PATH = Path(os.getenv("DB_PATH", str(PROJECT_ROOT / "data" / "quant.db")))
RAW_ROOT = Path(os.getenv("RAW_ROOT", str(PROJECT_ROOT / "data" / "raw")))
INCOMING_NEWS_DIR = Path(
    os.getenv("INCOMING_NEWS_DIR", str(PROJECT_ROOT / "data" / "incoming" / "news"))
)
LOG_DIR = Path(os.getenv("LOG_DIR", str(PROJECT_ROOT / "logs")))
BACKUP_DIR = PROJECT_ROOT / "data" / "backup"
LOCK_DIR = PROJECT_ROOT / "data" / "_locks"

TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "").strip()

for p in [RAW_ROOT, INCOMING_NEWS_DIR, LOG_DIR, BACKUP_DIR, LOCK_DIR, DB_PATH.parent]:
    p.mkdir(parents=True, exist_ok=True)

def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def now_ts():
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def normalize_trade_date(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in {"nan", "nat", "none"}:
        return None
    s = s.replace("-", "").replace("/", "").replace(":", "").replace(" ", "")
    return s[:8]

def log_job(conn, job_name, status, message):
    conn.execute(
        "INSERT INTO etl_job_log (job_name, status, message) VALUES (?, ?, ?)",
        (job_name, status, message)
    )
    conn.commit()

def upsert_watermark(conn, job_name, last_value):
    conn.execute("""
    INSERT OR REPLACE INTO ops_watermark (job_name, last_value, updated_at)
    VALUES (?, ?, CURRENT_TIMESTAMP)
    """, (job_name, last_value))
    conn.commit()

def backup_db():
    if not DB_PATH.exists():
        return None
    backup_file = BACKUP_DIR / f"quant_{now_ts()}.db"
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(backup_file)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    return str(backup_file)

def assert_writable(path_obj: Path):
    test_file = path_obj / f".write_test_{now_ts()}.tmp"
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("ok")
    test_file.unlink()

def acquire_lock(lock_name: str):
    lock_file = LOCK_DIR / f"{lock_name}.lock"
    if lock_file.exists():
        raise RuntimeError(f"检测到运行锁: {lock_file}，说明可能已有同类任务在运行")
    lock_file.write_text(str(os.getpid()), encoding="utf-8")
    return lock_file

def release_lock(lock_file: Path):
    if lock_file and lock_file.exists():
        lock_file.unlink()

def check_required_tables(conn, table_names):
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing = {row[0] for row in cur.fetchall()}
    missing = [t for t in table_names if t not in existing]
    if missing:
        raise RuntimeError(f"缺少数据表: {missing}")