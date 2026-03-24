from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.models.lightgbm_ranker_baseline import LightGBMRankerBaseline


def load_feature_list(feature_list_path: str | None) -> list[str] | None:
    if not feature_list_path:
        return None
    path = Path(feature_list_path)
    if not path.exists():
        raise FileNotFoundError(f"feature list file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        features = json.load(f)
    if not isinstance(features, list):
        raise ValueError("feature list json must be a list")
    return [str(x) for x in features]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run expanding walk-forward validation on model_panel_v1")
    parser.add_argument("--label-col", type=str, default="label_ret_5d_fwd_decile")
    parser.add_argument("--valid-days", type=int, default=3)
    parser.add_argument("--min-train-days", type=int, default=8)
    parser.add_argument("--step-days", type=int, default=3)
    parser.add_argument("--train-window-days", type=int, default=0)
    parser.add_argument("--missing-threshold", type=float, default=0.5)
    parser.add_argument("--num-boost-round", type=int, default=300)
    parser.add_argument(
        "--feature-list-path",
        type=str,
        default=None,
        help="optional json file containing a fixed feature list",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    feature_whitelist = load_feature_list(args.feature_list_path)

    trainer = LightGBMRankerBaseline()
    df = trainer.load_model_panel()

    if args.label_col not in df.columns:
        raise ValueError(f"label column not found: {args.label_col}")

    labeled = df[df[args.label_col].notna()].copy()
    labeled_dates = sorted(labeled["trade_date"].unique())

    if len(labeled_dates) < args.min_train_days + args.valid_days:
        raise ValueError(
            "not enough labeled trade dates for walk-forward: "
            f"labeled_dates={len(labeled_dates)}, "
            f"min_train_days={args.min_train_days}, valid_days={args.valid_days}"
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    group_id = (
        f"walkforward_{args.label_col}"
        f"_mt{int(round(args.missing_threshold * 100)):02d}"
        f"_vd{args.valid_days}"
        f"_mtd{args.min_train_days}"
        f"_sd{args.step_days}"
        f"_tw{args.train_window_days}"
        f"_{timestamp}"
    )
    group_dir = Path(r"D:\quant_system\outputs\research") / group_id
    group_dir.mkdir(parents=True, exist_ok=True)

    summary_rows = []
    window_no = 0
    split_idx = args.min_train_days

    while split_idx + args.valid_days <= len(labeled_dates):
        window_no += 1

        if args.train_window_days and args.train_window_days > 0:
            train_start_idx = max(0, split_idx - args.train_window_days)
        else:
            train_start_idx = 0

        train_dates = labeled_dates[train_start_idx:split_idx]
        valid_dates = labeled_dates[split_idx:split_idx + args.valid_days]

        run_id = (
            f"wf_w{window_no:02d}"
            f"_{args.label_col}"
            f"_mt{int(round(args.missing_threshold * 100)):02d}"
            f"_tr{train_dates[0].replace('-', '')}_{train_dates[-1].replace('-', '')}"
            f"_va{valid_dates[0].replace('-', '')}_{valid_dates[-1].replace('-', '')}"
        )

        result = trainer.train_from_date_sets(
            train_dates=train_dates,
            valid_dates=valid_dates,
            label_col=args.label_col,
            missing_threshold=args.missing_threshold,
            num_boost_round=args.num_boost_round,
            run_id=run_id,
            register_run=True,
            feature_whitelist=feature_whitelist,
        )

        summary_rows.append(
            {
                "window_no": window_no,
                "run_id": result.run_id,
                "train_start_date": result.metrics["train_start_date"],
                "train_end_date": result.metrics["train_end_date"],
                "valid_start_date": result.metrics["valid_start_date"],
                "valid_end_date": result.metrics["valid_end_date"],
                "feature_count": result.metrics["feature_count"],
                "best_iteration": result.metrics["best_iteration"],
                "mean_spearman_ic": result.metrics["metrics"]["mean_spearman_ic"],
                "ic_ir": result.metrics["metrics"]["ic_ir"],
                "mean_top_bottom_spread": result.metrics["metrics"]["mean_top_bottom_spread"],
                "run_dir": result.run_dir,
                "metrics_path": result.metrics_path,
            }
        )

        split_idx += args.step_days

    summary_df = pd.DataFrame(summary_rows)
    if summary_df.empty:
        raise ValueError("walk-forward produced no windows")

    summary_csv_path = group_dir / "walkforward_summary.csv"
    summary_json_path = group_dir / "walkforward_summary.json"

    summary_df.to_csv(summary_csv_path, index=False, encoding="utf-8-sig")

    summary_payload = {
        "group_id": group_id,
        "label_col": args.label_col,
        "valid_days": args.valid_days,
        "min_train_days": args.min_train_days,
        "step_days": args.step_days,
        "train_window_days": args.train_window_days,
        "missing_threshold": args.missing_threshold,
        "num_boost_round": args.num_boost_round,
        "feature_list_path": args.feature_list_path,
        "window_count": int(len(summary_df)),
        "mean_of_mean_spearman_ic": float(summary_df["mean_spearman_ic"].dropna().mean())
        if summary_df["mean_spearman_ic"].notna().any()
        else None,
        "mean_of_ic_ir": float(summary_df["ic_ir"].dropna().mean())
        if summary_df["ic_ir"].notna().any()
        else None,
        "mean_of_top_bottom_spread": float(summary_df["mean_top_bottom_spread"].dropna().mean())
        if summary_df["mean_top_bottom_spread"].notna().any()
        else None,
        "summary_csv_path": str(summary_csv_path),
    }

    with open(summary_json_path, "w", encoding="utf-8") as f:
        json.dump(summary_payload, f, ensure_ascii=False, indent=2)

    print("lightgbm walk-forward completed")
    print(json.dumps(summary_payload, ensure_ascii=False, indent=2))
    print("\nPer-window summary:")
    print(summary_df.to_string(index=False))


if __name__ == "__main__":
    main()