from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import Form, SrcFile, SyncIssue, SyncLog
from ..deps import viewer

router = APIRouter(prefix="/health", tags=["data health"], dependencies=[viewer])


def _count(db: Session, *where) -> int:
    return int(db.scalar(select(func.count()).select_from(Form).where(Form.deleted_at.is_(None), *where)) or 0)


_EXTRA_SQL = text("""
    select 'forms' as kind, k as header, count(*) as rows, count(distinct t.source_sheet_id) as tabs
      from forms t, jsonb_object_keys(t.extra) k where t.deleted_at is null group by k
    union all
    select 'escalations', k, count(*), count(distinct t.source_sheet_id)
      from escalations t, jsonb_object_keys(t.extra) k where t.deleted_at is null group by k
    order by 3 desc
""")


def extra_columns(db: Session) -> list[dict]:
    """Every source column that is not part of the standard schema. Nothing is dropped: the values of these
    columns are stored with each record (the `extra` field) and can be shown in the Data Explorer."""
    return [{"kind": r.kind, "header": r.header, "rows": int(r.rows), "tabs": int(r.tabs)}
            for r in db.execute(_EXTRA_SQL)]


@router.get("/data")
def data_health(db: Session = Depends(get_db)):
    live = _count(db)
    checks = [
        ("duplicates", "Forms with duplicate Job IDs (extra rows ignored)", _count(db, Form.dup_count > 0)),
        ("missing_received_date", "Forms with no Input Date", _count(db, Form.received_date.is_(None))),
        ("missing_editor", "Processed forms with no Editor Name",
         _count(db, Form.edit_date.is_not(None), Form.editor_id.is_(None))),
        ("missing_edit_status", "Processed forms with no Ops Status",
         _count(db, Form.edit_date.is_not(None), Form.edit_status.is_(None))),
        ("missing_qc_status", "QC member/date present but no QC Status",
         _count(db, (Form.qc_member_id.is_not(None)) | (Form.qc_date.is_not(None)), Form.qc_status.is_(None))),
    ]
    last = db.scalar(select(SyncLog).order_by(SyncLog.id.desc()).limit(1))
    last_ok = db.scalar(select(SyncLog).where(SyncLog.status.in_(["ok", "partial"]))
                        .order_by(SyncLog.id.desc()).limit(1))
    by_type, unmapped_cols, unmapped_status = [], [], []
    if last_ok:
        by_type = [{"type": t, "severity": s, "count": int(n)} for t, s, n in db.execute(
            select(SyncIssue.type, SyncIssue.severity, func.count()).where(SyncIssue.sync_id == last_ok.id)
            .group_by(SyncIssue.type, SyncIssue.severity).order_by(func.count().desc()))]
        unmapped_cols = sorted(set(db.scalars(select(SyncIssue.detail).where(
            SyncIssue.sync_id == last_ok.id, SyncIssue.type == "unmapped_column"))))
        unmapped_status = sorted(set(db.scalars(select(SyncIssue.detail).where(
            SyncIssue.sync_id == last_ok.id, SyncIssue.type == "unmapped_status"))))
    err_files = [{"id": f.id, "name": f.name} for f in db.scalars(select(SrcFile).where(SrcFile.status == "error"))]
    return {
        "forms_total": live,
        "checks": [{"key": k, "label": label, "count": n, "pct": round(100.0 * n / live, 2) if live else 0}
                   for k, label, n in checks],
        "last_sync": _log(last), "last_successful_sync": _log(last_ok),
        "issues_last_sync": by_type, "unmapped_columns": unmapped_cols, "unmapped_statuses": unmapped_status,
        "extra_columns": extra_columns(db),
        "header_repairs": sorted(set(db.scalars(select(SyncIssue.detail).where(SyncIssue.type == "header_repaired")))),
        "files_with_errors": err_files,
    }


def _log(s: SyncLog | None):
    if s is None:
        return None
    return {"id": s.id, "trigger": s.trigger, "status": s.status, "started_at": s.started_at,
            "finished_at": s.finished_at, "files_total": s.files_total, "files_scanned": s.files_scanned,
            "files_changed": s.files_changed, "rows_upserted": s.rows_upserted,
            "rows_rejected": s.rows_rejected, "error_text": s.error_text}


@router.get("/issues")
def issues(sync_id: int | None = None, type: str | None = None, severity: str | None = None,
           page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    if sync_id is None:
        sync_id = db.scalar(select(func.max(SyncLog.id)))
    where = [SyncIssue.sync_id == sync_id]
    if type:
        where.append(SyncIssue.type == type)
    if severity:
        where.append(SyncIssue.severity == severity)
    total = db.scalar(select(func.count()).select_from(SyncIssue).where(*where)) or 0
    rows = db.execute(
        select(SyncIssue, SrcFile.name).outerjoin(SrcFile, SrcFile.id == SyncIssue.file_id).where(*where)
        .order_by(SyncIssue.id).limit(page_size).offset((page - 1) * page_size))
    return {"sync_id": sync_id, "total": int(total), "page": page, "page_size": page_size,
            "rows": [{"id": i.id, "severity": i.severity, "type": i.type, "file": name, "row_no": i.row_no,
                      "detail": i.detail} for i, name in rows]}
