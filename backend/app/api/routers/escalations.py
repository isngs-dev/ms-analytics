from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from ...db import get_db
from ...services.cache import cached
from ...models import AppUser, DimClient, DimErrorCategory, DimPerson, DimProject, Escalation
from ...services import escalation_scope
from ...services.scope import Scope, scope_params
from ..deps import manager, viewer

router = APIRouter(prefix="/escalations", tags=["escalations"], dependencies=[viewer])
ACTION_STATUSES = ("open", "in_progress", "closed")


_where = escalation_scope.where


def _group(db: Session, where: list, key, label, joins=()):
    q = select(key.label("k"), label.label("name"), func.count().label("n")).select_from(Escalation)
    for target, on, outer in joins:
        q = q.outerjoin(target, on) if outer else q.join(target, on)
    q = q.where(*where).group_by(key, label).order_by(func.count().desc())
    return [{"id": r.k if isinstance(r.k, int) else None, "name": r.name, "count": int(r.n)}
            for r in db.execute(q)]


@router.get("/summary")
@cached("summary")
def summary(scope: Scope = Depends(scope_params), db: Session = Depends(get_db)):
    where = _where(scope)
    Ed = aliased(DimPerson)
    root = func.coalesce(func.nullif(func.lower(func.btrim(Escalation.root_cause)), ""), "(not recorded)")
    total = db.scalar(select(func.count()).select_from(Escalation).where(*where)) or 0
    closed = db.scalar(select(func.count()).select_from(Escalation).where(
        *where, Escalation.action_status == "closed")) or 0
    # the client's own words (Client Escalation / Feedback cell): the same wording counts together, most frequent first
    said = func.nullif(func.lower(func.btrim(Escalation.client_feedback)), "")
    by_said = [{"id": None, "name": r.name, "count": int(r.n)} for r in db.execute(
        select(func.min(func.btrim(Escalation.client_feedback)).label("name"), func.count().label("n"))
        .where(*where, said.is_not(None)).group_by(said).order_by(func.count().desc(), said).limit(15))]
    month = func.to_char(func.date_trunc("month", Escalation.raised_date), "YYYY-MM")
    return {
        "period": {"from": scope.date_from.isoformat(), "to": scope.date_to.isoformat()},
        "total": int(total), "closed": int(closed), "open": int(total - closed),
        "by_client": _group(db, where, Escalation.client_id, DimClient.name,
                            [(DimClient, DimClient.id == Escalation.client_id, False)]),
        "by_project": _group(db, where, Escalation.project_id, DimProject.name,
                             [(DimProject, DimProject.id == Escalation.project_id, False)]),
        "by_editor": _group(db, where, Escalation.editor_id, func.coalesce(Ed.name, "(unassigned)"),
                            [(Ed, Ed.id == Escalation.editor_id, True)]),
        "by_root_cause": _group(db, where, root, root),
        "by_client_escalation": by_said,
        "with_client_escalation": int(db.scalar(select(func.count()).select_from(Escalation).where(
            *where, said.is_not(None))) or 0),
        "by_error_category": _group(db, where, Escalation.error_category_id,
                                    func.coalesce(DimErrorCategory.name, "(uncategorised)"),
                                    [(DimErrorCategory, DimErrorCategory.id == Escalation.error_category_id, True)]),
        "by_action_status": _group(db, where, Escalation.action_status, Escalation.action_status),
        "by_month": sorted(_group(db, where, month, month), key=lambda r: r["name"]),
    }


@router.get("")
def list_escalations(scope: Scope = Depends(scope_params), search: str | None = None,
                     action_status: str | None = None, page: int = Query(1, ge=1),
                     page_size: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    Ed, Qc = aliased(DimPerson), aliased(DimPerson)
    where = _where(scope)
    if action_status:
        where.append(Escalation.action_status == action_status)
    if search and search.strip():
        like = f"%{search.strip()}%"
        where.append(or_(Escalation.job_id.ilike(like), Escalation.root_cause.ilike(like),
                         Escalation.client_feedback.ilike(like), DimProject.name.ilike(like)))
    base = (select(Escalation, DimClient.name, DimProject.name, Ed.name, Qc.name, DimErrorCategory.name)
            .select_from(Escalation).join(DimClient, DimClient.id == Escalation.client_id)
            .join(DimProject, DimProject.id == Escalation.project_id)
            .outerjoin(Ed, Ed.id == Escalation.editor_id).outerjoin(Qc, Qc.id == Escalation.qc_member_id)
            .outerjoin(DimErrorCategory, DimErrorCategory.id == Escalation.error_category_id))
    total = db.scalar(select(func.count()).select_from(Escalation)
                      .join(DimProject, DimProject.id == Escalation.project_id).where(*where)) or 0
    rows = []
    for e, client, project, editor, qc, cat in db.execute(
            base.where(*where).order_by(Escalation.raised_date.desc(), Escalation.id.desc())
            .limit(page_size).offset((page - 1) * page_size)):
        rows.append({"id": e.id, "client": client, "project": project, "job_id": e.job_id,
                     "raised_date": e.raised_date.isoformat() if e.raised_date else None,
                     "editor": editor, "qc_member": qc, "client_feedback": e.client_feedback,
                     "root_cause": e.root_cause, "error_category": cat,
                     "corrective_action": e.corrective_action, "preventive_action": e.preventive_action,
                     "action_status": e.action_status, "action_owner": e.action_owner,
                     "closed_date": e.closed_date.isoformat() if e.closed_date else None,
                     "remarks": e.remarks})
    return {"total": int(total), "page": page, "page_size": page_size, "rows": rows}


class EscalationPatch(BaseModel):
    action_status: str | None = None
    action_owner: str | None = None
    corrective_action: str | None = None
    preventive_action: str | None = None
    root_cause: str | None = None
    error_category_id: int | None = None
    closed_date: date | None = None
    remarks: str | None = None


@router.patch("/{escalation_id}")
def update_escalation(escalation_id: int, body: EscalationPatch, user: AppUser = manager,
                      db: Session = Depends(get_db)):
    """Corrective / preventive action tracking. Status / owner / closed date are app-only columns;
    a re-sync never erases action text with an empty sheet cell."""
    e = db.get(Escalation, escalation_id)
    if e is None or e.deleted_at is not None:
        raise HTTPException(404, "escalation not found")
    data = body.model_dump(exclude_unset=True)
    if "action_status" in data and data["action_status"] not in ACTION_STATUSES:
        raise HTTPException(422, f"action_status must be one of {ACTION_STATUSES}")
    if data.get("error_category_id") and db.get(DimErrorCategory, data["error_category_id"]) is None:
        raise HTTPException(422, "unknown error_category_id")
    if data.get("action_status") == "closed" and "closed_date" not in data:
        data["closed_date"] = date.today()
    for k, v in data.items():
        setattr(e, k, v)
    db.commit()
    return {"id": e.id, "action_status": e.action_status, "closed_date": e.closed_date}
