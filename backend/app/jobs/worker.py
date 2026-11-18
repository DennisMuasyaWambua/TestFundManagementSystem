"""The scheduled worker process.

APScheduler is the v1 choice from the build specification (Celery + Redis is the
alternative and needs no change to the jobs themselves, which are plain functions).

Two schedules:

* every day at 01:30, accrue profit, invoice rent and charge fees up to yesterday --
  profit for day D is only complete once D has ended;
* on the 1st of each month at 02:30, revalue foreign-currency balances at the closing
  rate of the month that has just ended.

Nothing here closes a period.  A month-end close is a deliberate act by FINANCE, who
must first clear the reconciliation breaks and the valuations the checklist lists, so
it stays a human decision on the /close screen.
"""

from __future__ import annotations

import logging
import signal
import sys
from datetime import date, timedelta
from types import FrameType

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.jobs.accrual_job import accrue_all, revalue_all

logger = logging.getLogger("fms.worker")


def yesterday(today: date | None = None) -> date:
    return (today or date.today()) - timedelta(days=1)


def last_day_of_previous_month(today: date | None = None) -> date:
    first_of_this_month = (today or date.today()).replace(day=1)
    return first_of_this_month - timedelta(days=1)


def daily_accruals() -> None:
    accrue_all(yesterday())


def monthly_revaluation() -> None:
    revalue_all(last_day_of_previous_month())


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone="Africa/Nairobi")
    scheduler.add_job(
        daily_accruals,
        CronTrigger(hour=1, minute=30),
        id="daily_accruals",
        # If the worker was down, run once on catch-up rather than once per missed day:
        # the accrual is cumulative, so a single run restores the correct total.
        coalesce=True,
        max_instances=1,
        misfire_grace_time=6 * 60 * 60,
    )
    scheduler.add_job(
        monthly_revaluation,
        CronTrigger(day=1, hour=2, minute=30),
        id="monthly_revaluation",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=24 * 60 * 60,
    )
    return scheduler


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = get_settings()
    logger.info("worker starting in %s", settings.env)

    scheduler = build_scheduler()

    def _stop(signum: int, _frame: FrameType | None) -> None:
        logger.info("signal %s received, shutting the scheduler down", signum)
        scheduler.shutdown(wait=True)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    scheduler.start()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
