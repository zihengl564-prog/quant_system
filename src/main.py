from pathlib import Path
from src.data_access.db_connection import SQLiteConnectionManager

PROJECT_ROOT = Path(__file__).resolve().parents[1]

RAW_DB_PATH = PROJECT_ROOT / "data" / "raw_data" / "raw_market_data.db"
STD_DB_PATH = PROJECT_ROOT / "data" / "standardized_data" / "research_data.db"

RAW_SQL_PATH = PROJECT_ROOT / "sql" / "create_raw_tables.sql"
STD_SQL_PATH = PROJECT_ROOT / "sql" / "create_standardized_tables.sql"
RAW_INDEX_SQL_PATH = PROJECT_ROOT / "sql" / "create_raw_indexes.sql"
STD_INDEX_SQL_PATH = PROJECT_ROOT / "sql" / "create_std_indexes.sql"


def read_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def init_raw_db() -> None:
    manager = SQLiteConnectionManager(str(RAW_DB_PATH))
    print("Initializing Raw DB...")
    manager.execute_script(read_sql(RAW_SQL_PATH))
    manager.execute_script(read_sql(RAW_INDEX_SQL_PATH))
    print("Raw DB initialized.")


def init_std_db() -> None:
    manager = SQLiteConnectionManager(str(STD_DB_PATH))
    print("Initializing Standardized DB...")
    manager.execute_script(read_sql(STD_SQL_PATH))
    manager.execute_script(read_sql(STD_INDEX_SQL_PATH))
    print("Standardized DB initialized.")


if __name__ == "__main__":
    init_raw_db()
    init_std_db()
    print("All databases initialized successfully.")