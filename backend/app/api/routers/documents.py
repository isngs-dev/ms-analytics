"""Every Drive document that was found, with what was read from it and how the rows reconcile."""
from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import (DimClient, DimProject, Escalation, Form, SrcFile, SrcRecord, SrcSheet, SyncIssue)
from ..deps import viewer

router = APIRouter(prefix="/documents", tags=["documents"], dependencies=[viewer])


def _drive_url(f: SrcFile) -> str:
    return f"https://docs.google.com/spreadsheets/d/{f.drive_file_id}/edit"


def _per_file(db: Session, model, fk) -> dict[int, int]:
    q = (select(SrcSheet.file_id, func.count()).select_from(model)
         .join(SrcSheet, SrcSheet.id == fk).where(model.deleted_at.is_(None)).group_by(SrcSheet.file_id))
    return {fid: int(n) for fid, n in db.execute(q)}


@router.get("")
def list_documents(search: str | None = None, year: int | None = None, quarter: int | None = None,
                   status: str | None = None, client_id: int | None = None,
                   sort: str = Query("name", pattern="^(name|modified|forms|issues|synced)$"),
                   order: str = Query("asc", pattern="^(asc|desc)$"),
                   page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
                   db: Session = Depends(get_db)):
    where = []
    if search and search.strip():
        where.append(SrcFile.name.ilike(f"%{search.strip()}%"))
    if year:
        where.append(SrcFile.year == year)
    if quarter:
        where.append(SrcFile.quarter == quarter)
    if status:
        where.append(SrcFile.status == status)
    if client_id:
        where.append(SrcFile.client_id == client_id)

    forms = _per_file(db, Form, Form.source_sheet_id)
    esc = _per_file(db, Escalation, Escalation.source_sheet_id)
    sheet_sums = {fid: (int(t), int(r), int(rej), int(ph), int(rl)) for fid, t, r, rej, ph, rl in db.execute(
        select(SrcSheet.file_id, func.count(), func.coalesce(func.sum(SrcSheet.rows_seen), 0),
               func.coalesce(func.sum(SrcSheet.rows_rejected), 0), func.coalesce(func.sum(SrcSheet.rows_placeholder), 0),
               func.coalesce(func.sum(SrcSheet.rows_loaded), 0)).group_by(SrcSheet.file_id))}
    read_tabs = {fid: int(n) for fid, n in db.execute(  # every tab except the credential ones is read
        select(SrcSheet.file_id, func.count()).where(SrcSheet.kind != "ignored").group_by(SrcSheet.file_id))}
    # latest issue count per file (from the most recent sync that touched it)
    latest: dict[int, tuple[int, int]] = {}
    for fid, sid, n in db.execute(select(SyncIssue.file_id, SyncIssue.sync_id, func.count())
                                  .where(SyncIssue.file_id.is_not(None)).group_by(SyncIssue.file_id, SyncIssue.sync_id)):
        if fid not in latest or sid > latest[fid][0]:
            latest[fid] = (sid, int(n))

    rows = db.execute(
        select(SrcFile, DimClient.name, DimProject.name).outerjoin(DimClient, DimClient.id == SrcFile.client_id)
        .outerjoin(DimProject, DimProject.id == SrcFile.project_id).where(*where)).all()
    items = []
    for f, client, project in rows:
        tabs, raw, rej, ph, loaded = sheet_sums.get(f.id, (0, 0, 0, 0, 0))
        items.append({
            "id": f.id, "name": f.name, "year": f.year, "quarter": f.quarter, "client": client,
            "project": project or ("multiple (from Form column)" if f.is_multi_project else None),
            "status": f.status, "drive_url": _drive_url(f), "modified_time": f.drive_modified_time,
            "last_synced_at": f.last_synced_at, "tabs": tabs, "tabs_read": read_tabs.get(f.id, 0),
            "forms": forms.get(f.id, 0), "escalations": esc.get(f.id, 0),
            "rows_loaded": loaded, "rows_rejected": rej, "rows_placeholder": ph,
            "issues": latest.get(f.id, (0, 0))[1],
        })
    keyf = {"name": lambda i: (i["name"] or "").lower(), "modified": lambda i: i["modified_time"] or 0,
            "forms": lambda i: i["forms"], "issues": lambda i: i["issues"], "synced": lambda i: i["last_synced_at"] or 0}[sort]
    items.sort(key=keyf, reverse=order == "desc")
    total = len(items)
    return {"total": total, "page": page, "page_size": page_size,
            "totals": {"forms": sum(i["forms"] for i in items),
                       "escalations": sum(i["escalations"] for i in items)},
            "rows": items[(page - 1) * page_size: page * page_size]}


@router.get("/facets")
def facets(db: Session = Depends(get_db)):
    return {"years": sorted({y for (y,) in db.execute(select(SrcFile.year).distinct()) if y}, reverse=True),
            "statuses": sorted({s for (s,) in db.execute(select(SrcFile.status).distinct())}),
            "clients": [{"id": i, "name": n} for i, n in db.execute(select(DimClient.id, DimClient.name).order_by(DimClient.name))]}


KIND_NOTE = {
    "ignored": "never read (credentials / switched off)",
    "master": "lookup lists (error categories etc.), kept as written",
    "reference": "every row stored as written, browse it here",
    "supplementary": "form-like tab: adds only Job IDs the main tabs do not have",
}


@router.get("/coverage")
def coverage(db: Session = Depends(get_db)):
    """What happened to every tab of every workbook: loaded into the analytics, kept as raw rows, or never read."""
    kinds = [{"kind": k, "tabs": int(t), "rows_seen": int(seen), "rows_loaded": int(loaded)}
             for k, t, seen, loaded in db.execute(select(
                 SrcSheet.kind, func.count(), func.coalesce(func.sum(SrcSheet.rows_seen), 0),
                 func.coalesce(func.sum(SrcSheet.rows_loaded), 0)).group_by(SrcSheet.kind).order_by(func.count().desc()))]
    return {
        "files": int(db.scalar(select(func.count()).select_from(SrcFile).where(SrcFile.status != "removed")) or 0),
        "tabs": sum(k["tabs"] for k in kinds),
        "kinds": [{**k, "note": KIND_NOTE.get(k["kind"])} for k in kinds],
        "raw_rows_stored": int(db.scalar(select(func.count()).select_from(SrcRecord)) or 0),
        "forms_from_supplementary_tabs": int(db.scalar(
            select(func.count()).select_from(Form).join(SrcSheet, SrcSheet.id == Form.source_sheet_id)
            .where(SrcSheet.kind == "supplementary", Form.deleted_at.is_(None))) or 0),
        "tabs_never_read": [{"file": f, "tab": t} for f, t in db.execute(
            select(SrcFile.name, SrcSheet.tab_name).join(SrcFile, SrcFile.id == SrcSheet.file_id)
            .where(SrcSheet.kind == "ignored").order_by(SrcFile.name).limit(5))],
    }


@router.get("/{doc_id}/tabs/{sheet_id}/rows")
def tab_rows(doc_id: int, sheet_id: int, search: str | None = None, page: int = Query(1, ge=1),
             page_size: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    """The rows of a reference tab exactly as written in the sheet (column names + cells)."""
    s = db.get(SrcSheet, sheet_id)
    if s is None or s.file_id != doc_id:
        raise HTTPException(404, "tab not found")
    where = [SrcRecord.sheet_id == sheet_id]
    if search and search.strip():
        where.append(cast(SrcRecord.cells, Text).ilike(f"%{search.strip()}%"))
    total = int(db.scalar(select(func.count()).select_from(SrcRecord).where(*where)) or 0)
    recs = db.execute(select(SrcRecord.row_no, SrcRecord.cells).where(*where).order_by(SrcRecord.row_no)
                      .limit(page_size).offset((page - 1) * page_size)).all()
    width = max([len(s.header or [])] + [len(c) for _, c in recs])
    return {"tab": s.tab_name, "kind": s.kind, "header": (s.header or []) + [""] * (width - len(s.header or [])),
            "total": total, "page": page, "page_size": page_size,
            "rows": [{"row_no": n, "cells": c + [""] * (width - len(c))} for n, c in recs]}


@router.get("/{doc_id}")
def document_detail(doc_id: int, db: Session = Depends(get_db)):
    f = db.get(SrcFile, doc_id)
    if f is None:
        raise HTTPException(404, "document not found")
    client = db.get(DimClient, f.client_id).name if f.client_id else None
    sheets = db.scalars(select(SrcSheet).where(SrcSheet.file_id == f.id).order_by(SrcSheet.id)).all()
    by_sheet = {}
    for model, key in ((Form, "forms"), (Escalation, "escalations")):
        for sid, n in db.execute(select(model.source_sheet_id, func.count()).where(
                model.source_sheet_id.in_([s.id for s in sheets] or [0]), model.deleted_at.is_(None))
                .group_by(model.source_sheet_id)):
            by_sheet.setdefault(sid, {})[key] = int(n)

    sheet_ids = [s.id for s in sheets] or [0]
    stats = db.execute(select(
        func.count(), func.min(Form.received_date), func.max(Form.received_date), func.count(func.distinct(Form.editor_id)),
        func.count(func.distinct(Form.project_id)), func.count().filter(Form.qc_date.is_not(None)),
        func.count().filter(Form.edit_date.is_not(None)), func.count().filter(Form.dup_count > 0))
        .where(Form.source_sheet_id.in_(sheet_ids), Form.deleted_at.is_(None))).one()
    statuses = [{"status": s or "(blank)", "count": int(n)} for s, n in db.execute(
        select(Form.edit_status, func.count()).where(Form.source_sheet_id.in_(sheet_ids), Form.deleted_at.is_(None))
        .group_by(Form.edit_status).order_by(func.count().desc()).limit(12))]
    projects = [{"project": p, "forms": int(n)} for p, n in db.execute(
        select(DimProject.name, func.count()).join(Form, Form.project_id == DimProject.id)
        .where(Form.source_sheet_id.in_(sheet_ids), Form.deleted_at.is_(None)).group_by(DimProject.name)
        .order_by(func.count().desc()).limit(20))]

    last_sync = db.scalar(select(func.max(SyncIssue.sync_id)).where(SyncIssue.file_id == f.id))
    issues = []
    issue_types = []
    if last_sync:
        issue_types = [{"type": t, "severity": s, "count": int(n)} for t, s, n in db.execute(
            select(SyncIssue.type, SyncIssue.severity, func.count()).where(
                SyncIssue.file_id == f.id, SyncIssue.sync_id == last_sync)
            .group_by(SyncIssue.type, SyncIssue.severity).order_by(func.count().desc()))]
        issues = [{"severity": i.severity, "type": i.type, "row_no": i.row_no, "detail": i.detail,
                   "tab": next((s.tab_name for s in sheets if s.id == i.sheet_id), None)}
                  for i in db.scalars(select(SyncIssue).where(SyncIssue.file_id == f.id, SyncIssue.sync_id == last_sync)
                                      .order_by(SyncIssue.id).limit(25))]
    return {
        "id": f.id, "name": f.name, "year": f.year, "quarter": f.quarter, "client": client, "status": f.status,
        "drive_url": _drive_url(f), "modified_time": f.drive_modified_time, "last_synced_at": f.last_synced_at,
        "summary": {"forms": int(stats[0]), "first_received": stats[1], "last_received": stats[2],
                    "editors": int(stats[3]), "projects": int(stats[4]), "with_qc": int(stats[5]),
                    "processed": int(stats[6]), "duplicates": int(stats[7])},
        "ops_statuses": statuses, "projects": projects,
        "tabs": [{
            "id": s.id, "tab": s.tab_name, "kind": s.kind, "counts_in_totals": s.include,
            "month": s.month_start.isoformat() if s.month_start else None, "header_row": s.header_row,
            "rows_seen": s.rows_seen, "rows_loaded": s.rows_loaded, "rows_rejected": s.rows_rejected,
            "rows_placeholder": s.rows_placeholder, "rows_duplicate": s.rows_duplicate,
            "forms": by_sheet.get(s.id, {}).get("forms", 0),
            "escalations": by_sheet.get(s.id, {}).get("escalations", 0),
            "note": KIND_NOTE.get(s.kind), "browsable": s.kind in ("reference", "master") and s.rows_loaded > 0,
        } for s in sheets],
        "issue_types": issue_types, "issues": issues,
    }
