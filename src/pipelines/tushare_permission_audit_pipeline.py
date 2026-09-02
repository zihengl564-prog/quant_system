from __future__ import annotations

import argparse
import json

from src.datasources.tushare_permission_auditor import (
    TusharePermissionAuditor,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Probe current Tushare API permissions using the token "
            "from the local .env and persist a local capability snapshot."
        )
    )
    parser.add_argument(
        "--probe-date",
        default="20240830",
        help=(
            "A known historical trading date used for lightweight "
            "permission probes, format YYYYMMDD."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    auditor = TusharePermissionAuditor()
    snapshot = auditor.audit_all(
        probe_date=args.probe_date,
    )

    print()
    print("=" * 72)
    print("Tushare Permission Audit")
    print("=" * 72)

    for item in snapshot["apis"]:
        marker = {
            "AVAILABLE": "[OK]",
            "NO_PERMISSION": "[NO]",
            "API_ERROR": "[ERR]",
            "NETWORK_ERROR": "[NET]",
        }.get(item["status"], "[?]")

        print(
            f"{marker:5} "
            f"{item['api_name']:<16} "
            f"{item['status']:<14} "
            f"rows={item['returned_rows']:<5} "
            f"code={item['code']} "
            f"{item['message']}"
        )

    print("-" * 72)
    print(
        json.dumps(
            snapshot["summary"],
            ensure_ascii=False,
            indent=2,
        )
    )
    print("-" * 72)
    print(
        "capability snapshot: "
        f"{auditor.capability_path}"
    )
    print("=" * 72)


if __name__ == "__main__":
    main()
