from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.strategies.turtle_v1 import TurtleV1Config, TurtleV1SignalBuilder


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXPORT_DIR = PROJECT_ROOT / "data" / "exports" / "turtle_v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build A-Turtle V1 daily signals from std_equity_daily."
    )
    parser.add_argument("--start", required=True, help="start date, e.g. 2024-06-01")
    parser.add_argument("--end", required=True, help="end date, e.g. 2024-08-31")
    parser.add_argument("--top-n", type=int, default=15)
    parser.add_argument("--min-list-days", type=int, default=120)
    parser.add_argument(
        "--min-avg-amount-20",
        type=float,
        default=50_000.0,
        help="20d minimum average amount; Tushare amount is normally in thousand RMB.",
    )
    parser.add_argument("--export-dir", default=str(DEFAULT_EXPORT_DIR))
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    config = TurtleV1Config(
        top_n=args.top_n,
        min_list_days=args.min_list_days,
        min_avg_amount_20=args.min_avg_amount_20,
    )
    builder = TurtleV1SignalBuilder(config=config)
    panel = builder.build(start_date=args.start, end_date=args.end)

    if panel.empty:
        raise RuntimeError("turtle v1 signal panel is empty")

    export_dir = Path(args.export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    start_tag = pd.to_datetime(args.start).strftime("%Y%m%d")
    end_tag = pd.to_datetime(args.end).strftime("%Y%m%d")

    candidates = (
        panel[panel["entry_signal_raw"]]
        .copy()
        .sort_values(["trade_date", "entry_rank", "ts_code"])
        .reset_index(drop=True)
    )
    selected = (
        panel[panel["entry_selected"]]
        .copy()
        .sort_values(["trade_date", "entry_rank", "ts_code"])
        .reset_index(drop=True)
    )

    daily_summary = panel.groupby("trade_date", as_index=False).agg(
        total_rows=("ts_code", "size"),
        universe_count=("universe_pass", "sum"),
        trend_count=("trend_pass", "sum"),
        breakout_count=("breakout_pass", "sum"),
        raw_signal_count=("entry_signal_raw", "sum"),
        selected_count=("entry_selected", "sum"),
    )

    candidates_path = export_dir / f"turtle_v1_candidates_{start_tag}_{end_tag}.csv"
    selected_path = export_dir / f"turtle_v1_selected_{start_tag}_{end_tag}.csv"
    summary_path = export_dir / f"turtle_v1_daily_summary_{start_tag}_{end_tag}.csv"

    candidates.to_csv(candidates_path, index=False, encoding="utf-8-sig")
    selected.to_csv(selected_path, index=False, encoding="utf-8-sig")
    daily_summary.to_csv(summary_path, index=False, encoding="utf-8-sig")

    summary = {
        "status": "SUCCESS",
        "strategy": "A-Turtle V1",
        "start_date": args.start,
        "end_date": args.end,
        "panel_rows": int(len(panel)),
        "trade_dates": int(panel["trade_date"].nunique()),
        "universe_rows": int(panel["universe_pass"].sum()),
        "raw_signal_rows": int(panel["entry_signal_raw"].sum()),
        "selected_rows": int(panel["entry_selected"].sum()),
        "selected_trade_dates": int(
            selected["trade_date"].nunique() if not selected.empty else 0
        ),
        "max_selected_per_day": int(daily_summary["selected_count"].max()),
        "candidates_csv": str(candidates_path),
        "selected_csv": str(selected_path),
        "daily_summary_csv": str(summary_path),
    }

    print()
    print("=" * 70)
    print("A-Turtle V1 Signal Pipeline")
    print("=" * 70)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("=" * 70)

    if not selected.empty:
        display_cols = [
            "trade_date",
            "ts_code",
            "security_name",
            "close",
            "close_adj",
            "ma20",
            "ma60",
            "entry_high_20",
            "atr20",
            "atr_pct",
            "breakout_strength",
            "entry_rank",
        ]
        display_cols = [col for col in display_cols if col in selected.columns]
        print()
        print("最近 20 条最终入选信号：")
        print(selected[display_cols].tail(20).to_string(index=False))
    else:
        print()
        print("WARNING: 当前区间没有产生最终入选信号。")


if __name__ == "__main__":
    main()
