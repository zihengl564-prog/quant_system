from __future__ import annotations

import argparse
import json
from pathlib import Path

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
    parser = argparse.ArgumentParser(description="Train minimal LightGBM ranker baseline on model_panel_v1")
    parser.add_argument("--label-col", type=str, default="label_ret_5d_fwd_decile")
    parser.add_argument("--valid-days", type=int, default=5)
    parser.add_argument("--missing-threshold", type=float, default=0.5)
    parser.add_argument("--num-boost-round", type=int, default=300)
    parser.add_argument("--run-id", type=str, default=None)
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
    result = trainer.train(
        label_col=args.label_col,
        valid_days=args.valid_days,
        missing_threshold=args.missing_threshold,
        num_boost_round=args.num_boost_round,
        run_id=args.run_id,
        register_run=True,
        feature_whitelist=feature_whitelist,
    )

    print("lightgbm baseline training completed")
    print(json.dumps(result.metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()