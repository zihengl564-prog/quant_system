from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config.settings import settings


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def append_log(log_path: Path, text: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(text)
        if not text.endswith("\n"):
            f.write("\n")


def print_and_log(log_path: Path, text: str) -> None:
    print(text, flush=True)
    append_log(log_path, text)


def build_command(python_exe: str, module_name: str, extra_args: list[str]) -> list[str]:
    return [python_exe, "-u", "-m", module_name, *extra_args]


def run_cmd(log_path: Path, cwd: Path, cmd: list[str], stop_on_failure: bool = True) -> int:
    print_and_log(log_path, "=" * 120)
    print_and_log(log_path, f"[TIME] {now_str()}")
    print_and_log(log_path, f"[CMD ] {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )

    if result.stdout:
        for line in result.stdout.splitlines():
            append_log(log_path, line)

    print_and_log(log_path, f"[RET ] return_code={result.returncode}")

    if result.returncode != 0 and stop_on_failure:
        raise RuntimeError(f"command failed: {' '.join(cmd)}")

    return result.returncode


def parse_audit_csv(audit_csv_path: Path) -> dict[str, Any]:
    if not audit_csv_path.exists():
        raise FileNotFoundError(f"audit csv not found: {audit_csv_path}")

    rows: list[dict[str, str]] = []
    with open(audit_csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    def int_field(row: dict[str, str], field: str) -> int:
        value = row.get(field, "0")
        return int(value) if value not in (None, "") else 0

    def get_trade_date(row: dict[str, str]) -> str:
        return row.get("trade_date_raw", "")

    missing_daily_dates = [get_trade_date(r) for r in rows if int_field(r, "has_ods_daily") == 0]
    missing_daily_basic_dates = [get_trade_date(r) for r in rows if int_field(r, "has_ods_daily_basic") == 0]
    missing_adj_factor_dates = [get_trade_date(r) for r in rows if int_field(r, "has_ods_adj_factor") == 0]
    missing_std_dates = [get_trade_date(r) for r in rows if int_field(r, "has_std_equity_daily") == 0]

    return {
        "open_trade_days": len(rows),
        "missing_daily_count": len(missing_daily_dates),
        "missing_daily_basic_count": len(missing_daily_basic_dates),
        "missing_adj_factor_count": len(missing_adj_factor_dates),
        "missing_std_count": len(missing_std_dates),
        "missing_daily_dates": missing_daily_dates,
        "missing_daily_basic_dates": missing_daily_basic_dates,
        "missing_adj_factor_dates": missing_adj_factor_dates,
        "missing_std_dates": missing_std_dates,
    }


def chunk_dates(dates: list[str], chunk_size: int) -> list[list[str]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    return [dates[i:i + chunk_size] for i in range(0, len(dates), chunk_size)]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Targeted repair for missing ods_adj_factor dates using audit CSV."
    )
    parser.add_argument("--start", required=True, help="YYYYMMDD")
    parser.add_argument("--end", required=True, help="YYYYMMDD")
    parser.add_argument(
        "--per-call-trade-days",
        type=int,
        default=1,
        help="How many missing trade dates to repair per adjustment_factors call. Recommend 1 or 3.",
    )
    parser.add_argument(
        "--audit-every-calls",
        type=int,
        default=20,
        help="Run audit after every N adjustment_factors calls.",
    )
    parser.add_argument(
        "--max-no-improve-rounds",
        type=int,
        default=3,
        help="Stop early if audit count does not improve for N consecutive audit rounds.",
    )
    parser.add_argument(
        "--sleep-seconds-between-calls",
        type=int,
        default=1,
        help="Sleep between adjustment_factors calls.",
    )
    parser.add_argument(
        "--run-tag",
        default=None,
        help="Optional suffix for log file naming.",
    )
    args = parser.parse_args()

    project_root = Path(settings.PROJECT_ROOT)
    python_exe = sys.executable
    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_tag = f"_{args.run_tag}" if args.run_tag else ""
    log_path = logs_dir / f"repair_adj_factor_gaps_{args.start}_{args.end}_{timestamp}{run_tag}.log"

    audit_csv_path = project_root / "data" / "exports" / "coverage" / f"daily_gap_audit_{args.start}_{args.end}.csv"

    print_and_log(log_path, "=" * 120)
    print_and_log(log_path, f"repair_adj_factor_gaps START at {now_str()}")
    print_and_log(log_path, f"project_root={project_root}")
    print_and_log(log_path, f"python_exe={python_exe}")
    print_and_log(log_path, f"start={args.start}, end={args.end}")
    print_and_log(log_path, f"log_path={log_path}")
    print_and_log(log_path, "=" * 120)

    # Initial audit
    run_cmd(
        log_path=log_path,
        cwd=project_root,
        cmd=build_command(
            python_exe,
            "src.pipelines.data_gap_audit_pipeline",
            ["--start", args.start, "--end", args.end],
        ),
        stop_on_failure=True,
    )

    audit_summary = parse_audit_csv(audit_csv_path)
    prev_missing_adj = audit_summary["missing_adj_factor_count"]
    no_improve_rounds = 0
    total_calls = 0

    print_and_log(
        log_path,
        f"[INIT AUDIT] missing_adj_factor_count={prev_missing_adj}, "
        f"missing_daily_count={audit_summary['missing_daily_count']}, "
        f"missing_daily_basic_count={audit_summary['missing_daily_basic_count']}, "
        f"missing_std_count={audit_summary['missing_std_count']}",
    )

    while True:
        missing_adj_dates = audit_summary["missing_adj_factor_dates"]
        if not missing_adj_dates:
            print_and_log(log_path, "[DONE] No missing adj_factor dates left.")
            break

        date_chunks = chunk_dates(missing_adj_dates, args.per_call_trade_days)

        print_and_log(
            log_path,
            f"[ROUND] current_missing_adj_factor_count={len(missing_adj_dates)}, "
            f"chunk_count={len(date_chunks)}, per_call_trade_days={args.per_call_trade_days}",
        )

        calls_in_this_round = 0

        for chunk in date_chunks:
            chunk_start = chunk[0]
            chunk_end = chunk[-1]
            total_calls += 1
            calls_in_this_round += 1

            print_and_log(
                log_path,
                f"[PROGRESS] call={total_calls}, repairing_adj_factor_dates={chunk}, "
                f"window={chunk_start}~{chunk_end}",
            )

            run_cmd(
                log_path=log_path,
                cwd=project_root,
                cmd=build_command(
                    python_exe,
                    "src.pipelines.historical_backfill_pipeline",
                    [
                        "--task", "adjustment_factors",
                        "--start", chunk_start,
                        "--end", chunk_end,
                        "--max-trade-days", str(len(chunk)),
                    ],
                ),
                stop_on_failure=False,
            )

            if args.sleep_seconds_between_calls > 0:
                time.sleep(args.sleep_seconds_between_calls)

            if calls_in_this_round % args.audit_every_calls == 0:
                print_and_log(log_path, "[CHECKPOINT] rebuild std + rerun audit")

                run_cmd(
                    log_path=log_path,
                    cwd=project_root,
                    cmd=build_command(
                        python_exe,
                        "src.pipelines.historical_backfill_pipeline",
                        [
                            "--task", "build_std_equity_daily",
                            "--start", args.start,
                            "--end", args.end,
                        ],
                    ),
                    stop_on_failure=False,
                )

                run_cmd(
                    log_path=log_path,
                    cwd=project_root,
                    cmd=build_command(
                        python_exe,
                        "src.pipelines.data_gap_audit_pipeline",
                        ["--start", args.start, "--end", args.end],
                    ),
                    stop_on_failure=True,
                )

                new_summary = parse_audit_csv(audit_csv_path)
                new_missing_adj = new_summary["missing_adj_factor_count"]
                delta = prev_missing_adj - new_missing_adj

                print_and_log(
                    log_path,
                    f"[AUDIT] missing_adj_factor_count: {prev_missing_adj} -> {new_missing_adj}, delta={delta}; "
                    f"missing_daily_count={new_summary['missing_daily_count']}; "
                    f"missing_daily_basic_count={new_summary['missing_daily_basic_count']}; "
                    f"missing_std_count={new_summary['missing_std_count']}",
                )

                if delta <= 0:
                    no_improve_rounds += 1
                else:
                    no_improve_rounds = 0

                audit_summary = new_summary
                prev_missing_adj = new_missing_adj

                if no_improve_rounds >= args.max_no_improve_rounds:
                    print_and_log(
                        log_path,
                        f"[STOP] No improvement for {no_improve_rounds} consecutive audit checkpoints.",
                    )
                    break

        # End of round: final rebuild + audit for this loop
        run_cmd(
            log_path=log_path,
            cwd=project_root,
            cmd=build_command(
                python_exe,
                "src.pipelines.historical_backfill_pipeline",
                [
                    "--task", "build_std_equity_daily",
                    "--start", args.start,
                    "--end", args.end,
                ],
            ),
            stop_on_failure=False,
        )

        run_cmd(
            log_path=log_path,
            cwd=project_root,
            cmd=build_command(
                python_exe,
                "src.pipelines.data_gap_audit_pipeline",
                ["--start", args.start, "--end", args.end],
            ),
            stop_on_failure=True,
        )

        new_summary = parse_audit_csv(audit_csv_path)
        new_missing_adj = new_summary["missing_adj_factor_count"]
        delta = prev_missing_adj - new_missing_adj

        print_and_log(
            log_path,
            f"[ROUND END AUDIT] missing_adj_factor_count: {prev_missing_adj} -> {new_missing_adj}, delta={delta}; "
            f"missing_daily_count={new_summary['missing_daily_count']}; "
            f"missing_daily_basic_count={new_summary['missing_daily_basic_count']}; "
            f"missing_std_count={new_summary['missing_std_count']}",
        )

        if delta <= 0:
            no_improve_rounds += 1
        else:
            no_improve_rounds = 0

        audit_summary = new_summary
        prev_missing_adj = new_missing_adj

        if not audit_summary["missing_adj_factor_dates"]:
            print_and_log(log_path, "[DONE] Adj factor gaps cleared after round-end audit.")
            break

        if no_improve_rounds >= args.max_no_improve_rounds:
            print_and_log(
                log_path,
                f"[STOP] No improvement for {no_improve_rounds} consecutive audit checkpoints/round-end audits.",
            )
            break

    final_summary = {
        "finished_at": now_str(),
        "missing_daily_count": audit_summary["missing_daily_count"],
        "missing_daily_basic_count": audit_summary["missing_daily_basic_count"],
        "missing_adj_factor_count": audit_summary["missing_adj_factor_count"],
        "missing_std_count": audit_summary["missing_std_count"],
        "log_path": str(log_path),
        "total_calls": total_calls,
    }

    print_and_log(log_path, "=" * 120)
    print_and_log(log_path, "[FINAL SUMMARY]")
    print_and_log(log_path, json.dumps(final_summary, ensure_ascii=False, indent=2))
    print_and_log(log_path, "=" * 120)

    print(f"log_path={log_path}", flush=True)
    print(json.dumps(final_summary, ensure_ascii=False, indent=2), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())