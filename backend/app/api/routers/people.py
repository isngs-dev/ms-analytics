from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...db import get_db
from ...services.cache import cached
from ...models import DimPerson
from ...services import metrics
from ...services.scope import Scope, scope_params
from ..deps import viewer

router = APIRouter(prefix="/people", tags=["people"], dependencies=[viewer])


def _period(scope: Scope) -> dict:
    return {"from": scope.date_from.isoformat(), "to": scope.date_to.isoformat()}


@router.get("/editors")
@cached("editor_productivity")
def editor_productivity(scope: Scope = Depends(scope_params), db: Session = Depends(get_db)):
    """Per-editor output (processed = every form they handled), plus the comparison chart data."""
    rows = [r for r in metrics.breakdown(db, scope, "editor")]
    ov = metrics.overview(db, scope)
    return {"period": _period(scope), "totals": ov, "editors": rows,
            "by_type": metrics.breakdown(db, scope, "editor_type")}


@router.get("/editors/{eid}")  # not `editor_id`: that name is a filter query param
@cached("editor_detail")
def editor_detail(eid: int, granularity: str = "week", scope: Scope = Depends(scope_params),
                  db: Session = Depends(get_db)):
    person = db.get(DimPerson, eid)
    if person is None:
        raise HTTPException(404, "editor not found")
    if granularity not in metrics.GRANULARITIES:
        raise HTTPException(422, f"granularity must be one of {metrics.GRANULARITIES}")
    sc = replace(scope, editor_id=eid)
    return {"editor": {"id": person.id, "name": person.name}, "period": _period(sc),
            "metrics": metrics.overview(db, sc),
            "by_client": metrics.breakdown(db, sc, "client"),
            "by_project": metrics.breakdown(db, sc, "project"),  # editor x client/project contribution
            "output": metrics.timeseries(db, sc, granularity)}


@router.get("/qc")
@cached("qc_members")
def qc_members(scope: Scope = Depends(scope_params), db: Session = Depends(get_db)):
    """QC work per member (completed, by date) and the QC backlog by project."""
    members = [r for r in metrics.breakdown(db, scope, "qc_member") if r["qc_completed"]]
    pending = [{"project_id": r["id"], "project": r["name"], "client": r["parent"],
                "qc_pending": r["qc_pending"], "qc_completed": r["qc_completed"]}
               for r in metrics.breakdown(db, replace(scope, qc_member_id=None), "project")
               if r["qc_pending"] or r["qc_completed"]]
    pending.sort(key=lambda r: -r["qc_pending"])
    return {"period": _period(scope), "members": members, "backlog_by_project": pending,
            "totals": {k: metrics.overview(db, scope)[k] for k in ("qc_completed", "qc_pending", "qc_pct")}}


@router.get("/qc/{mid}")
@cached("qc_member_detail")
def qc_member_detail(mid: int, granularity: str = "week", scope: Scope = Depends(scope_params),
                     db: Session = Depends(get_db)):
    person = db.get(DimPerson, mid)
    if person is None:
        raise HTTPException(404, "QC member not found")
    sc = replace(scope, qc_member_id=mid)
    return {"member": {"id": person.id, "name": person.name}, "period": _period(sc),
            "by_project": [r for r in metrics.breakdown(db, sc, "project") if r["qc_completed"]],
            "output": metrics.timeseries(db, sc, granularity if granularity in metrics.GRANULARITIES else "week")}
