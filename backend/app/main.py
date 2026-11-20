import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from . import scheduler
from .api.routers import admin, analytics, auth, documents, escalations, health, people, records, sync
from .config import settings
from .db import get_engine

# the sync reports its progress here (which workbook it is reading); a no-op when logging is already configured
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per Drive request drowned everything else


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.assert_safe()
    try:  # a restart kills a running sync; do not leave it "running" (that would block new syncs for hours)
        from datetime import datetime, timezone
        from sqlalchemy import update
        from .db import SessionLocal
        from .models import SyncLog
        with SessionLocal() as db:
            db.execute(update(SyncLog).where(SyncLog.status == "running").values(
                status="failed", finished_at=datetime.now(timezone.utc), error_text="Interrupted by an API restart"))
            db.commit()
    except Exception:
        pass
    try:  # a fresh database (a new Render deploy) has no column / status / sheet rules: add whatever default is missing
        from .db import SessionLocal
        from .seed.mapping import seed_mappings
        with SessionLocal() as db:
            seed_mappings(db)
            db.commit()
    except Exception:
        pass
    if settings.scheduler_enabled:
        minutes = settings.sync_interval_minutes
        try:  # the Admin screen's refresh interval wins over the env default
            from sqlalchemy import select
            from .db import SessionLocal
            from .models import AppSetting
            with SessionLocal() as db:
                s = db.scalar(select(AppSetting).where(AppSetting.key == "refresh_schedule"))
                minutes = int((s.value or {}).get("interval_minutes", minutes)) if s else minutes
        except Exception:
            pass
        scheduler.start(minutes)
    yield
    scheduler.stop()


app = FastAPI(title="MS Analytics API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

for r in (auth.router, analytics.router, people.router, escalations.router, records.router,
          documents.router, health.router, sync.router, admin.router):
    app.include_router(r, prefix="/api")


@app.get("/health")
def liveness():
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}
