from __future__ import annotations

import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "standardized_data" / "research_data.db"

TARGET_FILES = [
    PROJECT_ROOT / "src" / "features" / "feature_panel_builder.py",
    PROJECT_ROOT / "src" / "features" / "price_volume_feature_generator.py",
    PROJECT_ROOT / "src" / "features" / "liquidity_feature_generator.py",
    PROJECT_ROOT / "src" / "labels" / "return_label_generator.py",
    PROJECT_ROOT / "src" / "jobs" / "feature_jobs.py",
]


def print_section(title: str) -> None:
    print("\n" + "=" * 24 + f" {title} " + "=" * 24)


def main() -> None:
    print_section("PROJECT")
    print(f"project_root = {PROJECT_ROOT}")
    print(f"db_path      = {DB_PATH}")

    if not DB_PATH.exists():
        raise FileNotFoundError(f"standardized db not found: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        cur = conn.cursor()

        print_section("TABLES")
        tables = cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        for row in tables:
            print(row["name"])

        print_section("STD_EQUITY_DAILY SCHEMA")
        schema_rows = cur.execute("PRAGMA table_info(std_equity_daily)").fetchall()
        if not schema_rows:
            print("std_equity_daily not found or schema empty")
            return

        column_names = []
        for row in schema_rows:
            column_names.append(row["name"])
            print(
                f"cid={row['cid']:>2} | "
                f"name={row['name']:<24} | "
                f"type={str(row['type']):<12} | "
                f"notnull={row['notnull']} | "
                f"pk={row['pk']} | "
                f"default={row['dflt_value']}"
            )

        print_section("STD_EQUITY_DAILY SUMMARY")
        date_col = "trade_date" if "trade_date" in column_names else None
        id_col = "instrument" if "instrument" in column_names else (
            "ts_code" if "ts_code" in column_names else None
        )

        summary_exprs = ["COUNT(*) AS row_count"]
        if date_col:
            summary_exprs.extend([
                f"MIN({date_col}) AS min_trade_date",
                f"MAX({date_col}) AS max_trade_date",
                f"COUNT(DISTINCT {date_col}) AS trade_date_count",
            ])
        if id_col:
            summary_exprs.append(f"COUNT(DISTINCT {id_col}) AS instrument_count")

        summary_sql = "SELECT " + ", ".join(summary_exprs) + " FROM std_equity_daily"
        summary_row = cur.execute(summary_sql).fetchone()
        for key in summary_row.keys():
            print(f"{key} = {summary_row[key]}")

        print_section("STD_EQUITY_DAILY SAMPLE")
        preferred_cols = [
            "trade_date",
            "instrument",
            "ts_code",
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "vol",
            "amount",
            "turnover_rate",
            "turnover_rate_f",
            "volume_ratio",
            "pe_ttm",
            "pb",
            "ps_ttm",
            "dv_ttm",
            "total_mv",
            "circ_mv",
            "adj_factor",
        ]
        sample_cols = [c for c in preferred_cols if c in column_names]
        if not sample_cols:
            sample_cols = column_names[:10]

        sample_sql = f"SELECT {', '.join(sample_cols)} FROM std_equity_daily"
        order_cols = []
        if date_col:
            order_cols.append(date_col)
        if id_col:
            order_cols.append(id_col)
        if order_cols:
            sample_sql += " ORDER BY " + ", ".join(order_cols)
        sample_sql += " LIMIT 5"

        sample_rows = cur.execute(sample_sql).fetchall()
        print("sample_columns =", sample_cols)
        for idx, row in enumerate(sample_rows, start=1):
            print(f"[row {idx}]")
            for key in row.keys():
                print(f"  {key} = {row[key]}")

        print_section("TARGET FILE STATUS")
        for path in TARGET_FILES:
            rel_path = path.relative_to(PROJECT_ROOT)
            if path.exists():
                stat = path.stat()
                print(f"{rel_path} | EXISTS | size={stat.st_size} bytes")
            else:
                print(f"{rel_path} | MISSING")

    finally:
        conn.close()


if __name__ == "__main__":
    main()