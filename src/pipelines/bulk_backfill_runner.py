from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config.settings import settings


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def seconds_to_hms(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def append_log(log_path: Path, text: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(text)
        if not text.endswith("\n"):
            f.write("\n")


def print_and_log(log_path: Path, text: str) -> None:
    print(text, flush=True)
    append_log(log_path, text)


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def build_command(python_exe: str, module_name: str, extra_args: list[str]) -> list[str]:
    return [python_exe, "-u", "-m", module_name, *extra_args]


def truncate_text(text: str | None, max_len: int = 240) -> str | None:
    if text is None:
        return None
    text = str(text)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def query_recent_job_runs(limit: int = 10) -> list[dict[str, Any]]:
    db_path = Path(settings.STD_DB_PATH)
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, job_name, status, message, started_at, finished_at
            FROM job_runs
            ORDER BY id DESC
            LIMIT ?;
            """,
            (limit,),
        ).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "id": row["id"],
                    "job_name": row["job_name"],
                    "status": row["status"],
                    "message": truncate_text(row["message"], 240),
                    "started_at": row["started_at"],
                    "finished_at": row["finished_at"],
                }
            )
        return result
    finally:
        conn.close()


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

    summary = {
        "audit_csv_path": str(audit_csv_path),
        "open_trade_days": len(rows),
        "missing_daily_count": len(missing_daily_dates),
        "missing_daily_basic_count": len(missing_daily_basic_dates),
        "missing_adj_factor_count": len(missing_adj_factor_dates),
        "missing_std_count": len(missing_std_dates),
        "missing_daily_dates_sample": missing_daily_dates[:20],
        "missing_daily_basic_dates_sample": missing_daily_basic_dates[:20],
        "missing_adj_factor_dates_sample": missing_adj_factor_dates[:20],
        "missing_std_dates_sample": missing_std_dates[:20],
        "missing_daily_dates": missing_daily_dates,
        "missing_daily_basic_dates": missing_daily_basic_dates,
        "missing_adj_factor_dates": missing_adj_factor_dates,
        "missing_std_dates": missing_std_dates,
    }
    return summary


def total_gap_count(audit_summary: dict[str, Any] | None) -> int:
    if not audit_summary:
        return 10**9
    return (
        int(audit_summary.get("missing_daily_count", 0))
        + int(audit_summary.get("missing_daily_basic_count", 0))
        + int(audit_summary.get("missing_adj_factor_count", 0))
        + int(audit_summary.get("missing_std_count", 0))
    )


def is_gap_free(audit_summary: dict[str, Any] | None) -> bool:
    if not audit_summary:
        return False
    return (
        int(audit_summary.get("missing_daily_count", 0)) == 0
        and int(audit_summary.get("missing_daily_basic_count", 0)) == 0
        and int(audit_summary.get("missing_adj_factor_count", 0)) == 0
        and int(audit_summary.get("missing_std_count", 0)) == 0
    )


def extract_progress_from_line(line: str) -> dict[str, Any]:
    progress: dict[str, Any] = {}

    patterns = [
        r"processed_trade_dates\s*=\s*(\[[^\]]*\]).*?total_trade_dates\s*=\s*(\d+)",
        r"total_trade_dates\s*=\s*(\d+).*?processed_trade_dates\s*=\s*(\[[^\]]*\])",
    ]
    for idx, pattern in enumerate(patterns):
        match = re.search(pattern, line)
        if match:
            if idx == 0:
                processed_repr = match.group(1)
                total = int(match.group(2))
            else:
                total = int(match.group(1))
                processed_repr = match.group(2)

            date_count = len(re.findall(r"\d{8}", processed_repr))
            progress["processed_trade_dates_count"] = date_count
            progress["total_trade_dates"] = total
            progress["progress_pct"] = round(date_count / total * 100, 2) if total > 0 else None
            break

    trade_date_match = re.search(r"(\d{8})", line)
    if trade_date_match:
        progress["latest_trade_date_hint"] = trade_date_match.group(1)

    return progress


def run_cmd_streaming(
    *,
    step_name: str,
    cmd: list[str],
    cwd: Path,
    log_path: Path,
    status: dict[str, Any],
    status_path: Path,
    latest_status_path: Path,
    stop_on_failure: bool,
) -> int:
    status["current_step"] = step_name
    status["current_step_command"] = cmd
    status["current_step_started_at"] = now_str()
    status["_step_start_ts"] = time.time()
    status["last_child_output"] = None
    status["recent_job_runs"] = query_recent_job_runs(limit=8)
    write_json_atomic(status_path, status)
    write_json_atomic(latest_status_path, status)

    print_and_log(log_path, "=" * 120)
    print_and_log(log_path, f"[STEP START] {step_name} | {now_str()}")
    print_and_log(log_path, f"[CMD] {' '.join(cmd)}")

    process = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    try:
        assert process.stdout is not None
        last_progress_print_ts = 0.0

        for raw_line in process.stdout:
            line = raw_line.rstrip("\n")
            append_log(log_path, line)
            status["last_child_output"] = line[-500:] if line else line

            parsed = extract_progress_from_line(line)
            if parsed:
                status.update(parsed)

            now_ts = time.time()
            if now_ts - last_progress_print_ts >= 15:
                elapsed = seconds_to_hms(now_ts - status["_step_start_ts"])
                print(
                    f"[PROGRESS] {now_str()} | step={step_name} | elapsed={elapsed} | "
                    f"processed={status.get('processed_trade_dates_count')} / total={status.get('total_trade_dates')} | "
                    f"latest_hint={status.get('latest_trade_date_hint')}",
                    flush=True,
                )
                last_progress_print_ts = now_ts

            status["recent_job_runs"] = query_recent_job_runs(limit=8)
            write_json_atomic(status_path, status)
            write_json_atomic(latest_status_path, status)

        return_code = process.wait()
    finally:
        elapsed = seconds_to_hms(time.time() - status["_step_start_ts"])
        print_and_log(log_path, f"[STEP END] {step_name} | return_code={process.returncode} | elapsed={elapsed}")

    status["finished_steps"].append(
        {
            "step_name": step_name,
            "return_code": return_code,
            "finished_at": now_str(),
        }
    )
    if return_code != 0:
        status["failed_steps"].append(
            {
                "step_name": step_name,
                "return_code": return_code,
                "failed_at": now_str(),
            }
        )

    status["recent_job_runs"] = query_recent_job_runs(limit=8)
    write_json_atomic(status_path, status)
    write_json_atomic(latest_status_path, status)

    if return_code != 0 and stop_on_failure:
        raise RuntimeError(f"step failed: {step_name}, return_code={return_code}")

    return return_code


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fixed bulk backfill runner: broad scan + audit-driven adj repair + daily/basic/std repair + progress report."
    )
    parser.add_argument("--start", required=True, help="YYYYMMDD")
    parser.add_argument("--end", required=True, help="YYYYMMDD")
    parser.add_argument("--daily-batch-days", type=int, default=5, help="Initial broad-scan batch size for daily tasks")
    parser.add_argument("--max-auto-repair-rounds", type=int, default=20, help="Maximum repair rounds")
    parser.add_argument("--max-adj-dates-per-round", type=int, default=40, help="How many missing adj_factor dates to target per round")
    parser.add_argument("--max-daily-dates", type=int, default=60, help="repair_daily_gaps max ods_daily dates per round")
    parser.add_argument("--max-daily-basic-dates", type=int, default=60, help="repair_daily_gaps max ods_daily_basic dates per round")
    parser.add_argument("--max-std-dates", type=int, default=120, help="repair_daily_gaps max std dates per round")
    parser.add_argument("--sleep-seconds-between-rounds", type=int, default=3, help="Cooldown seconds between repair rounds")
    parser.add_argument("--no-improve-stop-rounds", type=int, default=3, help="Stop early if total gap count does not improve for N consecutive rounds")
    parser.add_argument("--skip-trade-calendar", action="store_true")
    parser.add_argument("--skip-stock-basic", action="store_true")
    parser.add_argument("--resume-only", action="store_true", help="Skip initial broad scan and only do repair loop")
    parser.add_argument("--run-tag", default=None)
    args = parser.parse_args()

    project_root = Path(settings.PROJECT_ROOT)
    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_tag = f"_{args.run_tag}" if args.run_tag else ""
    run_id = f"bulk_backfill_{args.start}_{args.end}_{run_ts}{run_tag}"

    log_path = logs_dir / f"{run_id}.log"
    status_path = logs_dir / f"{run_id}_status.json"
    latest_status_path = logs_dir / "bulk_backfill_latest_status.json"

    audit_csv_path = project_root / "data" / "exports" / "coverage" / f"daily_gap_audit_{args.start}_{args.end}.csv"
    python_exe = sys.executable

    status: dict[str, Any] = {
        "run_id": run_id,
        "status": "RUNNING",
        "started_at": now_str(),
        "project_root": str(project_root),
        "python_executable": python_exe,
        "start_date": args.start,
        "end_date": args.end,
        "daily_batch_days": args.daily_batch_days,
        "max_auto_repair_rounds": args.max_auto_repair_rounds,
        "max_adj_datasets_per_round": args.max_adj_dates_per_round,
        "max_daily_dates": args.max_daily_dates,
        "max_daily_basic_dates": args.max_daily_basic_dates,
        "max_std_dates": args.max_std_dates,
        "sleep_seconds_between_rounds": args.sleep_seconds_between_rounds,
        "no_improve_stop_rounds": args.no_improve_stop_rounds,
        "log_path": str(log_path),
        "status_path": str(status_path),
        "latest_status_path": str(latest_status_path),
        "current_step": None,
        "current_step_command": None,
        "repair_round": 0,
        "processed_trade_dates_count": None,
        "total_trade_dates": None,
        "progress_pct": None,
        "latest_trade_date_hint": None,
        "last_child_output": None,
        "latest_audit": None,
        "finished_steps": [],
        "failed_steps": [],
        "recent_job_runs": query_recent_job_runs(limit=8),
    }
    write_json_atomic(status_path, status)
    write_json_atomic(latest_status_path, status)

    print_and_log(log_path, "=" * 120)
    print_and_log(log_path, f"RUN_ID={run_id}")
    print_and_log(log_path, f"START={args.start}")
    print_and_log(log_path, f"END={args.end}")
    print_and_log(log_path, f"RESUME_ONLY={args.resume_only}")
    print_and_log(log_path, "=" * 120)

    try:
        # ------------------------------------------------------------------
        # 1) Initial broad scan
        # ------------------------------------------------------------------
        if not args.resume_only:
            if not args.skip_trade_calendar:
                run_cmd_streaming(
                    step_name="refresh_trade_calendar",
                    cmd=build_command(
                        python_exe,
                        "src.pipelines.historical_backfill_pipeline",
                        ["--task", "trade_calendar", "--start", args.start, "--end", args.end],
                    ),
                    cwd=project_root,
                    log_path=log_path,
                    status=status,
                    status_path=status_path,
                    latest_status_path=latest_status_path,
                    stop_on_failure=False,
                )

            if not args.skip_stock_basic:
                run_cmd_streaming(
                    step_name="refresh_stock_basic",
                    cmd=build_command(
                        python_exe,
                        "src.pipelines.historical_backfill_pipeline",
                        ["--task", "stock_basic"],
                    ),
                    cwd=project_root,
                    log_path=log_path,
                    status=status,
                    status_path=status_path,
                    latest_status_path=latest_status_path,
                    stop_on_failure=False,
                )

            run_cmd_streaming(
                step_name="backfill_daily_quotes",
                cmd=build_command(
                    python_exe,
                    "src.pipelines.historical_backfill_pipeline",
                    [
                        "--task", "daily_quotes",
                        "--start", args.start,
                        "--end", args.end,
                        "--max-trade-days", str(args.daily_batch_days),
                    ],
                ),
                cwd=project_root,
                log_path=log_path,
                status=status,
                status_path=status_path,
                latest_status_path=latest_status_path,
                stop_on_failure=False,
            )

            run_cmd_streaming(
                step_name="backfill_daily_fundamentals",
                cmd=build_command(
                    python_exe,
                    "src.pipelines.historical_backfill_pipeline",
                    [
                        "--task", "daily_fundamentals",
                        "--start", args.start,
                        "--end", args.end,
                        "--max-trade-days", str(args.daily_batch_days),
                    ],
                ),
                cwd=project_root,
                log_path=log_path,
                status=status,
                status_path=status_path,
                latest_status_path=latest_status_path,
                stop_on_failure=False,
            )

            # 初始 broad scan 仍保留，但后续不再靠它自动补 adj 缺口
            run_cmd_streaming(
                step_name="backfill_adjustment_factors_initial",
                cmd=build_command(
                    python_exe,
                    "src.pipelines.historical_backfill_pipeline",
                    [
                        "--task", "adjustment_factors",
                        "--start", args.start,
                        "--end", args.end,
                        "--max-trade-days", str(args.daily_batch_days),
                    ],
                ),
                cwd=project_root,
                log_path=log_path,
                status=status,
                status_path=status_path,
                latest_status_path=latest_status_path,
                stop_on_failure=False,
            )

        # ------------------------------------------------------------------
        # 2) First std build + first audit
        # ------------------------------------------------------------------
        run_cmd_streaming(
            step_name="build_std_equity_daily_initial",
            cmd=build_command(
                python_exe,
                "src.pipelines.historical_backfill_pipeline",
                ["--task", "build_std_equity_daily", "--start", args.start, "--end", args.end],
            ),
            cwd=project_root,
            log_path=log_path,
            status=status,
            status_path=status_path,
            latest_status_path=latest_status_path,
            stop_on_failure=False,
        )

        run_cmd_streaming(
            step_name="gap_audit_round_0",
            cmd=build_command(
                python_exe,
                "src.pipelines.data_gap_audit_pipeline",
                ["--start", args.start, "--end", args.end],
            ),
            cwd=project_root,
            log_path=log_path,
            status=status,
            status_path=status_path,
            latest_status_path=latest_status_path,
            stop_on_failure=True,
        )

        latest_audit = parse_audit_csv(audit_csv_path)
        status["latest_audit"] = latest_audit
        write_json_atomic(status_path, status)
        write_json_atomic(latest_status_path, status)

        prev_total_gap = total_gap_count(latest_audit)
        no_improve_rounds = 0

        # ------------------------------------------------------------------
        # 3) Auto repair loop
        # ------------------------------------------------------------------
        for round_idx in range(1, args.max_auto_repair_rounds + 1):
            status["repair_round"] = round_idx
            write_json_atomic(status_path, status)
            write_json_atomic(latest_status_path, status)

            if is_gap_free(latest_audit):
                print_and_log(log_path, f"[DONE] gap-free before repair_round={round_idx}")
                break

            print_and_log(
                log_path,
                f"[ROUND START] repair_round={round_idx} | "
                f"gap[daily={latest_audit['missing_daily_count']}, "
                f"daily_basic={latest_audit['missing_daily_basic_count']}, "
                f"adj={latest_audit['missing_adj_factor_count']}, "
                f"std={latest_audit['missing_std_count']}]",
            )

            # --------------------------------------------------------------
            # 3.1 Targeted adj_factor repair: use real missing dates
            # --------------------------------------------------------------
            missing_adj_dates = latest_audit.get("missing_adj_factor_dates", [])
            target_adj_dates = missing_adj_dates[: args.max_adj_dates_per_round]

            if target_adj_dates:
                total_target = len(target_adj_dates)
                for idx, trade_date in enumerate(target_adj_dates, start=1):
                    print_and_log(
                        log_path,
                        f"[PROGRESS] repair_round={round_idx} | "
                        f"targeted_adj_factor {idx}/{total_target} | trade_date={trade_date}",
                    )
                    run_cmd_streaming(
                        step_name=f"repair_round_{round_idx}_adj_factor_{trade_date}",
                        cmd=build_command(
                            python_exe,
                            "src.pipelines.historical_backfill_pipeline",
                            [
                                "--task", "adjustment_factors",
                                "--start", trade_date,
                                "--end", trade_date,
                                "--max-trade-days", "1",
                            ],
                        ),
                        cwd=project_root,
                        log_path=log_path,
                        status=status,
                        status_path=status_path,
                        latest_status_path=latest_status_path,
                        stop_on_failure=False,
                    )

            # --------------------------------------------------------------
            # 3.2 Repair daily / daily_basic / std gaps
            # --------------------------------------------------------------
            need_repair_daily_family = (
                latest_audit.get("missing_daily_count", 0) > 0
                or latest_audit.get("missing_daily_basic_count", 0) > 0
                or latest_audit.get("missing_std_count", 0) > 0
            )

            if need_repair_daily_family:
                run_cmd_streaming(
                    step_name=f"repair_round_{round_idx}_repair_daily_gaps",
                    cmd=build_command(
                        python_exe,
                        "src.pipelines.repair_daily_gaps_pipeline",
                        [
                            "--start", args.start,
                            "--end", args.end,
                            "--mode", "all",
                            "--max-daily-dates", str(args.max_daily_dates),
                            "--max-daily-basic-dates", str(args.max_daily_basic_dates),
                            "--max-std-dates", str(args.max_std_dates),
                        ],
                    ),
                    cwd=project_root,
                    log_path=log_path,
                    status=status,
                    status_path=status_path,
                    latest_status_path=latest_status_path,
                    stop_on_failure=False,
                )

            # --------------------------------------------------------------
            # 3.3 Rebuild std after repairs
            # --------------------------------------------------------------
            run_cmd_streaming(
                step_name=f"repair_round_{round_idx}_rebuild_std_equity_daily",
                cmd=build_command(
                    python_exe,
                    "src.pipelines.historical_backfill_pipeline",
                    ["--task", "build_std_equity_daily", "--start", args.start, "--end", args.end],
                ),
                cwd=project_root,
                log_path=log_path,
                status=status,
                status_path=status_path,
                latest_status_path=latest_status_path,
                stop_on_failure=False,
            )

            # --------------------------------------------------------------
            # 3.4 Audit after round
            # --------------------------------------------------------------
            run_cmd_streaming(
                step_name=f"gap_audit_after_repair_round_{round_idx}",
                cmd=build_command(
                    python_exe,
                    "src.pipelines.data_gap_audit_pipeline",
                    ["--start", args.start, "--end", args.end],
                ),
                cwd=project_root,
                log_path=log_path,
                status=status,
                status_path=status_path,
                latest_status_path=latest_status_path,
                stop_on_failure=True,
            )

            new_audit = parse_audit_csv(audit_csv_path)
            status["latest_audit"] = new_audit
            write_json_atomic(status_path, status)
            write_json_atomic(latest_status_path, status)

            new_total_gap = total_gap_count(new_audit)
            delta_total_gap = prev_total_gap - new_total_gap

            print_and_log(
                log_path,
                f"[ROUND END] repair_round={round_idx} | "
                f"total_gap: {prev_total_gap} -> {new_total_gap} | delta={delta_total_gap} | "
                f"gap[daily={new_audit['missing_daily_count']}, "
                f"daily_basic={new_audit['missing_daily_basic_count']}, "
                f"adj={new_audit['missing_adj_factor_count']}, "
                f"std={new_audit['missing_std_count']}]",
            )

            if new_total_gap < prev_total_gap:
                no_improve_rounds = 0
            else:
                no_improve_rounds += 1

            latest_audit = new_audit
            prev_total_gap = new_total_gap

            if is_gap_free(latest_audit):
                print_and_log(log_path, f"[DONE] gap-free after repair_round={round_idx}")
                break

            if no_improve_rounds >= args.no_improve_stop_rounds:
                print_and_log(
                    log_path,
                    f"[STOP] no improvement for {no_improve_rounds} consecutive rounds.",
                )
                break

            if args.sleep_seconds_between_rounds > 0:
                time.sleep(args.sleep_seconds_between_rounds)

        # ------------------------------------------------------------------
        # 4) Final status
        # ------------------------------------------------------------------
        if is_gap_free(latest_audit):
            final_status = "SUCCESS"
        elif status["failed_steps"]:
            final_status = "PARTIAL_SUCCESS"
        else:
            final_status = "PARTIAL_SUCCESS"

        status["status"] = final_status
        status["finished_at"] = now_str()
        status["recent_job_runs"] = query_recent_job_runs(limit=10)
        write_json_atomic(status_path, status)
        write_json_atomic(latest_status_path, status)

        print_and_log(log_path, "=" * 120)
        print_and_log(log_path, "[FINAL SUMMARY]")
        print_and_log(log_path, json.dumps(status, ensure_ascii=False, indent=2))
        print_and_log(log_path, "=" * 120)

        print(f"run_id={run_id}", flush=True)
        print(f"log_path={log_path}", flush=True)
        print(f"status_path={status_path}", flush=True)
        print(f"latest_status_path={latest_status_path}", flush=True)
        print(f"final_status={final_status}", flush=True)

        return 0 if final_status == "SUCCESS" else 2

    except Exception as e:
        status["status"] = "FAILED"
        status["error_type"] = type(e).__name__
        status["error_message"] = str(e)
        status["finished_at"] = now_str()
        status["recent_job_runs"] = query_recent_job_runs(limit=10)
        write_json_atomic(status_path, status)
        write_json_atomic(latest_status_path, status)

        print_and_log(log_path, "=" * 120)
        print_and_log(log_path, "[FATAL ERROR]")
        print_and_log(log_path, f"{type(e).__name__}: {e}")
        print_and_log(log_path, "=" * 120)

        print(f"run_id={run_id}", flush=True)
        print(f"log_path={log_path}", flush=True)
        print(f"status_path={status_path}", flush=True)
        print(f"latest_status_path={latest_status_path}", flush=True)
        print("final_status=FAILED", flush=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())