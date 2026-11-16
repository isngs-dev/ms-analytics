"""In-process scheduled refresh. Single-worker deployment assumed (one scheduler per process)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from .config import settings
from .services.sync_runner import run_sync_job

JOB_ID = "scheduled-sync"
_scheduler: BackgroundScheduler | None = None


def start(interval_minutes: int | None = None) -> None:
    global _scheduler
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(run_sync_job, "interval", minutes=interval_minutes or settings.sync_interval_minutes,
                       id=JOB_ID, args=["schedule"], max_instances=1, coalesce=True,
                       next_run_time=datetime.now(timezone.utc) + timedelta(seconds=45))  # also check right after start
    _scheduler.start()


def reschedule(interval_minutes: int) -> bool:
    if _scheduler is None:
        return False
    _scheduler.reschedule_job(JOB_ID, trigger="interval", minutes=interval_minutes)
    return True


def stop() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
