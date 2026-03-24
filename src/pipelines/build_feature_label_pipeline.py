from __future__ import annotations

import argparse
import json

from src.jobs.feature_jobs import build_feature_label_job


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build minimal feature/label/model panels from std_equity_daily")
    parser.add_argument("--start", dest="start_date", type=str, default=None, help="e.g. 20240102 or 2024-01-02")
    parser.add_argument("--end", dest="end_date", type=str, default=None, help="e.g. 20240131 or 2024-01-31")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = build_feature_label_job(
        start_date=args.start_date,
        end_date=args.end_date,
    )

    print("feature/label pipeline completed")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()