from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "standardized_data" / "research_data.db"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "research"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not DB_PATH.exists():
        raise FileNotFoundError(f"db not found: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query(
            "SELECT * FROM model_panel_v1 ORDER BY trade_date, ts_code",
            conn,
        )
    finally:
        conn.close()

    if df.empty:
        raise ValueError("model_panel_v1 is empty")

    feature_cols = [c for c in df.columns if c.startswith("feat_")]
    label_cols = [c for c in df.columns if c.startswith("label_")]

    duplicate_row_count = int(df.duplicated(subset=["trade_date", "ts_code"]).sum())
    duplicate_key_group_count = int(
        df.groupby(["trade_date", "ts_code"]).size().gt(1).sum()
    )

    missing_rows = []
    for col in df.columns:
        missing_count = int(df[col].isna().sum())
        missing_ratio = float(missing_count / len(df))
        if col in feature_cols:
            kind = "feature"
        elif col in label_cols:
            kind = "label"
        else:
            kind = "dimension"
        missing_rows.append(
            {
                "column": col,
                "kind": kind,
                "missing_count": missing_count,
                "missing_ratio": missing_ratio,
            }
        )
    missing_df = pd.DataFrame(missing_rows).sort_values(
        ["kind", "missing_ratio", "column"],
        ascending=[True, False, True],
    )

    daily_coverage = (
        df.groupby("trade_date")
        .agg(
            rows=("ts_code", "size"),
            unique_codes=("ts_code", "nunique"),
            label_1d_nonnull=("label_ret_1d_fwd", lambda s: int(s.notna().sum())),
            label_5d_nonnull=("label_ret_5d_fwd", lambda s: int(s.notna().sum())),
            label_5d_decile_nonnull=("label_ret_5d_fwd_decile", lambda s: int(s.notna().sum())),
        )
        .reset_index()
        .sort_values("trade_date")
    )

    decile_distribution = (
        df["label_ret_5d_fwd_decile"]
        .value_counts(dropna=False)
        .rename_axis("label_ret_5d_fwd_decile")
        .reset_index(name="count")
        .sort_values("label_ret_5d_fwd_decile", na_position="last")
    )

    high_missing_features = missing_df[
        (missing_df["kind"] == "feature") & (missing_df["missing_ratio"] >= 0.5)
    ].copy()

    summary = {
        "db_path": str(DB_PATH),
        "row_count": int(len(df)),
        "feature_count": int(len(feature_cols)),
        "label_count": int(len(label_cols)),
        "trade_date_count": int(df["trade_date"].nunique()),
        "instrument_count": int(df["ts_code"].nunique()),
        "min_trade_date": str(df["trade_date"].min()),
        "max_trade_date": str(df["trade_date"].max()),
        "duplicate_row_count": duplicate_row_count,
        "duplicate_key_group_count": duplicate_key_group_count,
        "label_1d_nonnull_rows": int(df["label_ret_1d_fwd"].notna().sum()) if "label_ret_1d_fwd" in df.columns else None,
        "label_5d_nonnull_rows": int(df["label_ret_5d_fwd"].notna().sum()) if "label_ret_5d_fwd" in df.columns else None,
        "label_5d_decile_nonnull_rows": int(df["label_ret_5d_fwd_decile"].notna().sum()) if "label_ret_5d_fwd_decile" in df.columns else None,
        "high_missing_feature_count_ge_50pct": int(len(high_missing_features)),
    }

    summary_path = OUTPUT_DIR / "model_panel_v1_audit_summary.json"
    missing_path = OUTPUT_DIR / "model_panel_v1_missingness.csv"
    daily_path = OUTPUT_DIR / "model_panel_v1_daily_coverage.csv"
    decile_path = OUTPUT_DIR / "model_panel_v1_label_5d_decile_distribution.csv"

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    missing_df.to_csv(missing_path, index=False, encoding="utf-8-sig")
    daily_coverage.to_csv(daily_path, index=False, encoding="utf-8-sig")
    decile_distribution.to_csv(decile_path, index=False, encoding="utf-8-sig")

    print("model_panel_v1 audit completed")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    print("\nTop 10 highest-missing feature columns:")
    top_missing = missing_df[missing_df["kind"] == "feature"].head(10)
    if top_missing.empty:
        print("no feature columns found")
    else:
        print(top_missing.to_string(index=False))


if __name__ == "__main__":
    main()