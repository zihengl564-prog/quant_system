from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from src.datasources.tushare_provider import TushareProvider


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXPORT_DIR = PROJECT_ROOT / "data" / "exports" / "coverage"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit Tushare core API permissions used by the data preparation layer."
    )
    parser.add_argument(
        "--probe-date",
        default="20240102",
        help="用于轻量探测的历史交易日，格式 YYYYMMDD，默认 20240102",
    )
    parser.add_argument(
        "--probe-ts-code",
        default="000001.SZ",
        help="用于轻量探测的股票代码，默认 000001.SZ",
    )
    parser.add_argument(
        "--export-dir",
        default=str(DEFAULT_EXPORT_DIR),
        help="审计结果输出目录",
    )
    return parser.parse_args()


def build_summary(results: list[dict]) -> dict:
    status_counts: dict[str, int] = {}
    for row in results:
        status = str(row.get("status", "UNKNOWN"))
        status_counts[status] = status_counts.get(status, 0) + 1

    denied = [
        row["api_name"]
        for row in results
        if row.get("status") == "PERMISSION_DENIED"
    ]
    unavailable = [
        row["api_name"]
        for row in results
        if row.get("status") != "AVAILABLE"
    ]

    if not unavailable:
        overall_status = "HEALTHY"
    elif denied and len(denied) == len(results):
        overall_status = "PERMISSION_BLOCKED"
    else:
        overall_status = "DEGRADED"

    return {
        "overall_status": overall_status,
        "status_counts": status_counts,
        "permission_denied_apis": denied,
        "unavailable_apis": unavailable,
    }


def main() -> None:
    args = parse_args()
    provider = TushareProvider()

    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    results = provider.audit_core_permissions(
        probe_trade_date=args.probe_date,
        probe_ts_code=args.probe_ts_code,
    )
    summary = build_summary(results)

    report = {
        "checked_at": checked_at,
        "probe_date": args.probe_date,
        "probe_ts_code": args.probe_ts_code,
        **summary,
        "apis": results,
        "notes": {
            "permission_error_code": 2002,
            "meaning": "Tushare 官方 HTTP 文档定义 code=2002 为权限问题。",
            "behavior": (
                "权限错误不会自动重试；对应接口应停止重复回填，"
                "其他未受影响的接口仍可继续工作。"
            ),
        },
    }

    export_dir = Path(args.export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    timestamped_path = export_dir / f"tushare_permission_audit_{timestamp}.json"
    latest_path = export_dir / "tushare_permission_status_latest.json"

    text = json.dumps(report, ensure_ascii=False, indent=2)
    timestamped_path.write_text(text, encoding="utf-8")
    latest_path.write_text(text, encoding="utf-8")

    print("=" * 72)
    print("Tushare 核心接口权限审计")
    print("=" * 72)
    print(f"检查时间: {checked_at}")
    print(f"总体状态: {report['overall_status']}")
    print("-" * 72)

    for row in results:
        message = row.get("message") or ""
        print(
            f"{row['api_name']:<14} "
            f"{row['status']:<24} "
            f"code={row.get('code')} rows={row.get('rows', 0)} "
            f"{message}"
        )

    print("-" * 72)
    print(f"latest: {latest_path}")
    print(f"archive: {timestamped_path}")
    print("=" * 72)


if __name__ == "__main__":
    main()
