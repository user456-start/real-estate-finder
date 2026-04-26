"""
APScheduler — runs the ETL pipeline every 6 hours.

Job state is persisted in Postgres so:
  - Jobs survive app restarts (won't re-run if the process was down for < 6h)
  - Missed runs are caught up on startup (misfire_grace_time = 1h)

Schedule: 00:00, 06:00, 12:00, 18:00 Dubai time (Asia/Dubai = UTC+4, no DST)

Manual trigger (runs immediately, outside the schedule):
    uv run python -m app.services.scheduler --now
"""

from __future__ import annotations

import asyncio
import logging

from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = _build_scheduler()
    return _scheduler


def _build_scheduler() -> AsyncIOScheduler:
    jobstores = {
        # Persist job state in Postgres — survives restarts
        "default": SQLAlchemyJobStore(url=settings.DATABASE_URL),
    }
    executors = {
        "default": AsyncIOExecutor(),
    }
    job_defaults = {
        "coalesce":          True,   # if multiple runs were missed, fire only once
        "max_instances":     1,      # never run the same job twice in parallel
        "misfire_grace_time": 3600,  # catch up if the app was down < 1h
    }
    return AsyncIOScheduler(
        jobstores=jobstores,
        executors=executors,
        job_defaults=job_defaults,
        timezone="Asia/Dubai",
    )


def start_scheduler() -> None:
    """Register jobs and start the scheduler. Call once from FastAPI lifespan."""
    from app.services.etl import run_etl          # avoid circular imports
    from app.agents.digest import run_digest

    scheduler = get_scheduler()

    # Remove stale job definitions so config changes take effect on restart
    scheduler.remove_all_jobs()

    # ETL — every 6 hours
    scheduler.add_job(
        func=run_etl,
        trigger=CronTrigger(
            hour="0,6,12,18",
            minute="0",
            timezone="Asia/Dubai",
        ),
        id="etl_pipeline",
        name="Dubai listings ETL (6h)",
        replace_existing=True,
    )

    # Daily digest email — 08:00 Dubai time
    scheduler.add_job(
        func=run_digest,
        trigger=CronTrigger(
            hour="8",
            minute="0",
            timezone="Asia/Dubai",
        ),
        id="daily_digest",
        name="Daily property digest email",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "Scheduler started — ETL at 00:00/06:00/12:00/18:00, digest at 08:00 Dubai time. "
        "Next ETL: %s | Next digest: %s",
        scheduler.get_job("etl_pipeline").next_run_time,
        scheduler.get_job("daily_digest").next_run_time,
    )


def stop_scheduler() -> None:
    """Gracefully shut down — waits for the running job to finish."""
    sched = get_scheduler()
    if sched.running:
        sched.shutdown(wait=True)
        logger.info("Scheduler stopped.")


async def trigger_now() -> None:
    """Run the ETL pipeline immediately (for testing / manual backfill)."""
    from app.services.etl import run_etl
    logger.info("Manual ETL trigger — starting now")
    await run_etl()


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if "--now" in sys.argv:
        asyncio.run(trigger_now())
    else:
        print("Usage: uv run python -m app.services.scheduler --now")
        print("To run on schedule, start the FastAPI app instead.")
