from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import DimClient, DimPerson, DimProject, Form, SyncLog
from ...services import compare as cmp
from ...services.cache import cached
from ...services import metrics
from ...services import quality as quality_svc
from ...services import trends
from ...services.scope import Scope, scope_params
from ..deps import viewer

router = APIRouter(tags=["analytics"], dependencies=[viewer])


def _period(scope: Scope) -> dict:
    return {"from": scope.date_from.isoformat(), "to": scope.date_to.isoformat()}


@cached("filter_values")
def _filter_values(db: Session) -> dict:
    live = Form.deleted_at.is_(None)  # clients / projects / people / statuses that only exist in removed years stay out
    people = db.execute(select(DimPerson.id, DimPerson.name).order_by(DimPerson.name)).all()
    editors = set(db.scalars(select(Form.editor_id).where(Form.editor_id.is_not(None), live).distinct()))
    qcs = set(db.scalars(select(Form.qc_member_id).where(Form.qc_member_id.is_not(None), live).distinct()))
    live_clients = set(db.scalars(select(Form.client_id).where(live).distinct()))
    live_projects = set(db.scalars(select(Form.project_id).where(live).distinct()))
    return {
        "clients": [{"id": i, "name": n} for i, n in db.execute(select(DimClient.id, DimClient.name)
                                                                 .order_by(DimClient.name)) if i in live_clients],
        "projects": [{"id": i, "name": n, "client_id": c, "qc_applicable": bool(
            o if o is not None else d)} for i, n, c, o, d in db.execute(
            select(DimProject.id, DimProject.name, DimProject.client_id,
                   DimProject.qc_applicable_override, DimProject.qc_detected).order_by(DimProject.name))
            if i in live_projects],
        "editors": [{"id": i, "name": n} for i, n in people if i in editors],
        "qc_members": [{"id": i, "name": n} for i, n in people if i in qcs],
        "edit_statuses": sorted(s for s in db.scalars(select(Form.edit_status).where(live).distinct()) if s),
        "qc_statuses": sorted(s for s in db.scalars(select(Form.qc_status).where(live).distinct()) if s),
        "editor_types": sorted(s for s in db.scalars(select(Form.editor_type).where(live).distinct()) if s),
        "data_range": dict(zip(("from", "to"), [d.isoformat() if d else None for d in db.execute(
            select(func.min(Form.received_date), func.max(Form.received_date)).where(live)).one()])),
    }


@router.get("/meta/filters")
def filter_options(db: Session = Depends(get_db)):
    out = dict(_filter_values(db=db))  # heavy part cached; the sync stamp is always fresh
    last = db.scalar(select(SyncLog).where(SyncLog.status.in_(["ok", "partial"])).order_by(SyncLog.id.desc()).limit(1))
    out["last_sync"] = {"id": last.id, "finished_at": last.finished_at, "status": last.status} if last else None
    return out


@router.get("/analytics/overview")
@cached("overview")
def overview(scope: Scope = Depends(scope_params), db: Session = Depends(get_db)):
    return {"period": _period(scope), "filters": scope.dims(), "metrics": metrics.overview(db, scope),
            "definitions": metrics.DEFINITIONS}


@router.get("/analytics/breakdown")
@cached("breakdown")
def breakdown(by: str = Query(..., description=" | ".join(metrics.BREAKDOWNS)),
              scope: Scope = Depends(scope_params), db: Session = Depends(get_db)):
    if by not in metrics.BREAKDOWNS:
        raise HTTPException(422, f"by must be one of {metrics.BREAKDOWNS}")
    return {"period": _period(scope), "by": by, "rows": metrics.breakdown(db, scope, by)}


@router.get("/analytics/quality")
@cached("quality")
def quality(by: str = Query("client", pattern="^(client|project)$"),
            scope: Scope = Depends(scope_params), db: Session = Depends(get_db)):
    """How many reports were edited, and how many of them came back (client escalation)."""
    return {"period": _period(scope), **quality_svc.quality(db, scope, by)}


@router.get("/analytics/forms-compare")
@cached("forms_compare")
def forms_compare(vs: str = Query("previous", pattern="^(previous|yoy)$"),
                  scope: Scope = Depends(scope_params), db: Session = Depends(get_db)):
    """Every form name inside every project, the selected period against the previous period (or last year)."""
    return {"filters": scope.dims(), **trends.forms_compare(db, scope, vs)}


@router.get("/analytics/change-drivers")
@cached("change_drivers")
def change_drivers(metric: str, cur_from: date, cur_to: date, prev_from: date, prev_to: date,
                   limit: int = Query(8, ge=1, le=30),
                   scope: Scope = Depends(scope_params), db: Session = Depends(get_db)):
    """The forms behind a difference between two periods (what a comparison badge shows on hover)."""
    if metric not in metrics.METRICS:
        raise HTTPException(422, f"metric must be one of {metrics.METRICS}")
    if cur_from > cur_to or prev_from > prev_to:
        raise HTTPException(422, "a period starts after it ends")
    return {"filters": scope.dims(),
            **trends.change_drivers(db, scope, metric, (cur_from, cur_to), (prev_from, prev_to), limit)}


@router.get("/analytics/forms-months")
@cached("forms_months")
def forms_months(metric: str = Query("received", description=" | ".join(trends.DROP_METRICS)),
                 scope: Scope = Depends(scope_params), db: Session = Depends(get_db)):
    """Every form of every project, month by month across the selected period (e.g. the whole of 2026)."""
    if metric not in trends.DROP_METRICS:
        raise HTTPException(422, f"metric must be one of {trends.DROP_METRICS}")
    return {"filters": scope.dims(), **trends.forms_by_month(db, scope, metric)}


@router.get("/analytics/week-grid")
@cached("week_grid")
def week_grid(metric: str = Query("received", description=" | ".join(trends.WEEK_METRICS)),
              scope: Scope = Depends(scope_params), db: Session = Depends(get_db)):
    """Monday-Sunday weeks of every month in the period, a cell per day, each week against the previous week and
    against the same week of the month before."""
    if metric not in trends.WEEK_METRICS:
        raise HTTPException(422, f"metric must be one of {trends.WEEK_METRICS}")
    return {"filters": scope.dims(), **trends.week_grid(db, scope, metric)}


@router.get("/analytics/month-drivers")
@cached("month_drivers")
def month_drivers(metric: str = Query("received", description=" | ".join(trends.DROP_METRICS)),
                  scope: Scope = Depends(scope_params), db: Session = Depends(get_db)):
    """Month by month: which projects / forms pulled the volume down (and which pushed it up)."""
    if metric not in trends.DROP_METRICS:
        raise HTTPException(422, f"metric must be one of {trends.DROP_METRICS}")
    return {"filters": scope.dims(), **trends.month_drivers(db, scope, metric)}


@router.get("/analytics/timeseries")
@cached("timeseries")
def timeseries(granularity: str = "day", scope: Scope = Depends(scope_params),
               db: Session = Depends(get_db)):
    if granularity not in metrics.GRANULARITIES:
        raise HTTPException(422, f"granularity must be one of {metrics.GRANULARITIES}")
    if len(metrics.buckets(scope.date_from, scope.date_to, granularity)) > 1500:
        raise HTTPException(422, "range too large for this granularity")
    return {"period": _period(scope), "granularity": granularity,
            "points": metrics.timeseries(db, scope, granularity)}


@router.get("/analytics/projects/{pid}")  # not `project_id`: that name is a filter query param
@cached("project_detail")
def project_detail(pid: int, scope: Scope = Depends(scope_params), db: Session = Depends(get_db)):
    p = db.get(DimProject, pid)
    if p is None:
        raise HTTPException(404, "project not found")
    from dataclasses import replace
    sc = replace(scope, project_ids=(pid,), client_ids=())
    return {"project": {"id": p.id, "name": p.name, "client_id": p.client_id,
                        "qc_applicable": bool(p.qc_applicable_override if p.qc_applicable_override is not None
                                              else p.qc_detected)},
            "period": _period(sc), "metrics": metrics.overview(db, sc),
            "by_editor": metrics.breakdown(db, sc, "editor"),
            "by_form": metrics.breakdown(db, sc, "form"),
            "trend": metrics.timeseries(db, sc, "month" if (sc.date_to - sc.date_from).days > 120 else "week")}


@router.get("/analytics/compare")
@cached("compare")
def compare(mode: str = "month_vs_prev_month", anchor: date | None = None,
            scope: Scope = Depends(scope_params), db: Session = Depends(get_db)):
    if mode not in cmp.MODES:
        raise HTTPException(422, f"mode must be one of {cmp.MODES}")
    custom = (scope.date_from, scope.date_to) if mode in ("custom", "yoy") else None
    # a period that ends in the future (e.g. year=2026 in November) must not anchor on an empty future month
    return cmp.compare(db, scope, mode, anchor or min(scope.date_to, date.today()), custom)


@router.get("/analytics/alerts")
@cached("alerts")
def alerts(anchor: date | None = None, scope: Scope = Depends(scope_params), db: Session = Depends(get_db)):
    """Month-over-month volume / pending alerts.

    Evaluated on the last COMPLETE month at or before the anchor, so a half-finished current month
    is never compared against a full one (that would flag every project as a volume drop).
    """
    anchor = anchor or min(scope.date_to, date.today())
    if (anchor + timedelta(days=1)).day != 1:  # anchor is not a month end
        anchor = anchor.replace(day=1) - timedelta(days=1)
    month = cmp.compare(db, scope, "month_vs_prev_month", anchor)
    return {"anchor": anchor.isoformat(), "comparison": {"current": month["current"],
                                                         "previous": month["previous"]},
            "alerts": month["alerts"]}
