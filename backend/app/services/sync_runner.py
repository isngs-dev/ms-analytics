"""Starts sync runs (manual or scheduled) with a single-run guard."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal
from ..etl.sources import SheetSource
from ..etl.sync import run_sync
from ..models import SyncLog
from . import cache

_lock = threading.Lock()
_mock_cache: SheetSource | None = None
STALE_AFTER = timedelta(hours=2)  # a 'running' row older than this is considered dead


class SyncUnavailable(RuntimeError):
    pass


def get_source() -> SheetSource:
    global _mock_cache
    if settings.data_source == "mock":
        if _mock_cache is None:
            from ..seed.mock import build_mock_source
            _mock_cache = build_mock_source()
        return _mock_cache
    if settings.data_source == "drive":
        from ..etl.drive import DriveConfigError, DriveSource
        try:
            return DriveSource.from_settings(settings)  # built per run so credentials never go stale
        except DriveConfigError as e:
            raise SyncUnavailable(str(e))
    raise SyncUnavailable(f"unknown DATA_SOURCE '{settings.data_source}'")


from . import cache  # noqa: E402


def running_sync(db) -> SyncLog | None:
    cutoff = datetime.now(timezone.utc) - STALE_AFTER
    return db.scalar(select(SyncLog).where(SyncLog.status == "running", SyncLog.started_at > cutoff)
                     .order_by(SyncLog.id.desc()).limit(1))


def run_sync_job(trigger: str, force: bool = False) -> None:
    """Entry point for background tasks and the scheduler. Never raises."""
    if not _lock.acquire(blocking=False):
        return
    cache.begin_sync()
    try:
        with SessionLocal() as db:
            if running_sync(db):
                return
            try:
                run_sync(db, get_source(), trigger=trigger, force=force)
            except Exception as exc:  # leave a trace in sync_log instead of dying silently
                db.rollback()
                db.add(SyncLog(trigger=trigger, status="failed", finished_at=datetime.now(timezone.utc),
                               error_text=f"{type(exc).__name__}: {exc}"[:2000]))
                db.commit()
    finally:
        cache.end_sync()
        _lock.release()
