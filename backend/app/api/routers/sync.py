from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import settings
from ...db import get_db
from ...models import AppSetting, SyncLog
from ...services import sync_runner
from ...security import ROLES
from ..deps import current_user, viewer
from .health import _log

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("", status_code=202)
def sync_now(background: BackgroundTasks, force: bool = Query(False, description="re-read unchanged files"),
             db: Session = Depends(get_db), user=Depends(current_user)):
    """Manual 'Sync now'. Runs in the background; poll GET /sync/status for progress.
    Anyone signed in may start the normal check (it only reads Drive for what changed); the full re-read needs a manager."""
    if force and ROLES.get(user.role, 0) < ROLES["manager"]:
        raise HTTPException(403, "manager role required for a full re-sync")
    if settings.data_source != "mock":
        try:
            sync_runner.get_source()  # validates credentials / config without touching the network
        except sync_runner.SyncUnavailable as e:
            raise HTTPException(503, str(e))
    if sync_runner.running_sync(db):
        raise HTTPException(409, "A sync is already running")
    background.add_task(sync_runner.run_sync_job, "manual", force)
    return {"accepted": True}


@router.get("/status", dependencies=[viewer])
def status(db: Session = Depends(get_db)):
    last = db.scalar(select(SyncLog).order_by(SyncLog.id.desc()).limit(1))
    out = _log(last)
    if out and last.files_total:
        out["progress_pct"] = round(100.0 * last.files_scanned / last.files_total, 1)
    last_change = db.scalar(select(SyncLog).where(SyncLog.status.in_(["ok", "partial"]), SyncLog.files_changed > 0)
                            .order_by(SyncLog.id.desc()).limit(1))
    hb = db.get(AppSetting, "sync_heartbeat")
    interval = db.get(AppSetting, "refresh_schedule")
    return {"running": bool(sync_runner.running_sync(db)), "data_source": settings.data_source, "last": out,
            "last_change": _log(last_change), "heartbeat": hb.value if hb else None,
            "auto_sync": {"enabled": settings.scheduler_enabled,
                          "interval_minutes": (interval.value or {}).get("interval_minutes") if interval else settings.sync_interval_minutes}}


@router.get("/logs", dependencies=[viewer])
def logs(limit: int = Query(20, ge=1, le=200), db: Session = Depends(get_db)):
    return {"logs": [_log(s) for s in db.scalars(select(SyncLog).order_by(SyncLog.id.desc()).limit(limit))]}
