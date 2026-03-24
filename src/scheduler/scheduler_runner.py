import argparse

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from src.common.logging_utils import get_app_logger, get_error_logger
from src.pipelines.daily_update_pipeline import DailyUpdatePipeline


class SchedulerRunner:
    def __init__(
        self,
        hour: int,
        minute: int,
        calendar_lookback_days: int,
        calendar_forward_days: int,
        repair_lookback_days: int,
        max_daily_dates: int,
        max_daily_basic_dates: int,
        max_std_dates: int,
    ):
        self.hour = hour
        self.minute = minute

        self.calendar_lookback_days = calendar_lookback_days
        self.calendar_forward_days = calendar_forward_days
        self.repair_lookback_days = repair_lookback_days
        self.max_daily_dates = max_daily_dates
        self.max_daily_basic_dates = max_daily_basic_dates
        self.max_std_dates = max_std_dates

        self.app_logger = get_app_logger()
        self.error_logger = get_error_logger()

    def _job(self):
        self.app_logger.info(
            "[SchedulerRunner] 触发 daily_update_v1 定时任务"
        )

        pipeline = DailyUpdatePipeline()
        pipeline.run(
            as_of_date=None,
            calendar_lookback_days=self.calendar_lookback_days,
            calendar_forward_days=self.calendar_forward_days,
            repair_lookback_days=self.repair_lookback_days,
            max_daily_dates=self.max_daily_dates,
            max_daily_basic_dates=self.max_daily_basic_dates,
            max_std_dates=self.max_std_dates,
        )

    def run(self):
        scheduler = BlockingScheduler()

        scheduler.add_job(
            self._job,
            trigger=CronTrigger(hour=self.hour, minute=self.minute),
            id="daily_update_v1_job",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        print("=" * 80)
        print("Scheduler 已启动")
        print(f"每日触发时间（本机时间）: {self.hour:02d}:{self.minute:02d}")
        print("任务: daily_update_v1")
        print("-" * 80)
        print(f"calendar_lookback_days={self.calendar_lookback_days}")
        print(f"calendar_forward_days={self.calendar_forward_days}")
        print(f"repair_lookback_days={self.repair_lookback_days}")
        print(f"max_daily_dates={self.max_daily_dates}")
        print(f"max_daily_basic_dates={self.max_daily_basic_dates}")
        print(f"max_std_dates={self.max_std_dates}")
        print("=" * 80)

        self.app_logger.info(
            f"[SchedulerRunner] Scheduler 启动成功，每日 {self.hour:02d}:{self.minute:02d} 运行"
        )

        try:
            scheduler.start()
        except KeyboardInterrupt:
            self.app_logger.warning("[SchedulerRunner] Scheduler 被用户中断")
            raise
        except Exception as e:
            self.error_logger.exception(
                f"[SchedulerRunner] Scheduler 运行失败: {type(e).__name__}: {e}"
            )
            raise


def main():
    parser = argparse.ArgumentParser(description="Scheduler Runner for Daily Update V1")
    parser.add_argument("--run-once", action="store_true", help="只运行一次，不启动常驻调度")
    parser.add_argument("--as-of", default=None, help="run-once 时的基准日，格式 YYYYMMDD")
    parser.add_argument("--hour", type=int, default=18, help="每日调度小时，默认 18")
    parser.add_argument("--minute", type=int, default=10, help="每日调度分钟，默认 10")
    parser.add_argument("--calendar-lookback-days", type=int, default=60)
    parser.add_argument("--calendar-forward-days", type=int, default=30)
    parser.add_argument("--repair-lookback-days", type=int, default=20)
    parser.add_argument("--max-daily-dates", type=int, default=3)
    parser.add_argument("--max-daily-basic-dates", type=int, default=3)
    parser.add_argument("--max-std-dates", type=int, default=5)
    args = parser.parse_args()

    if args.run_once:
        pipeline = DailyUpdatePipeline()
        pipeline.run(
            as_of_date=args.as_of,
            calendar_lookback_days=args.calendar_lookback_days,
            calendar_forward_days=args.calendar_forward_days,
            repair_lookback_days=args.repair_lookback_days,
            max_daily_dates=args.max_daily_dates,
            max_daily_basic_dates=args.max_daily_basic_dates,
            max_std_dates=args.max_std_dates,
        )
        return

    runner = SchedulerRunner(
        hour=args.hour,
        minute=args.minute,
        calendar_lookback_days=args.calendar_lookback_days,
        calendar_forward_days=args.calendar_forward_days,
        repair_lookback_days=args.repair_lookback_days,
        max_daily_dates=args.max_daily_dates,
        max_daily_basic_dates=args.max_daily_basic_dates,
        max_std_dates=args.max_std_dates,
    )
    runner.run()


if __name__ == "__main__":
    main()