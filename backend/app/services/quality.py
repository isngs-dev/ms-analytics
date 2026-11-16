"""Client-feedback quality of the reports that were edited.

Cohort = every report the editors worked on in the selected period: forms with a Transaction Date in the
period, whatever the outcome (Finalized, Edited & Saved, Accepted, Hold ...). This is the `processed` metric.
Counting only the narrow "Edited & Saved" status would leave out most of the work, because the bulk of
edited reports end up as Finalized. How many of them carry the "Edited & Saved" status is reported as
`marked_edited`. Same filters as every other metric. A report "came back" when the client escalated it (an Escalation row for the same client / project / Job ID)
(rework is not part of any analytics). Quality is the share that did not:

    quality_pct = (edited - came_back) / edited

The feedback itself may arrive after the period, so the figure for the latest period can still improve.
"""
from __future__ import annotations

from sqlalchemy import exists, func, literal, select
from sqlalchemy.orm import Session

from ..models import DimClient, DimProject, Escalation, Form
from . import metrics
from .scope import Scope

DEFINITION = ("Reports edited = every report with a Transaction Date in the period, whatever its final status. "
              "Quality = reports that did not come back (no client escalation) ÷ reports edited. "
              "Feedback is matched on client + project + Job ID.")


def _columns(marked_edited):
    esc = exists().where(Escalation.deleted_at.is_(None), Escalation.client_id == Form.client_id,
                         Escalation.project_id == Form.project_id, Escalation.job_id == Form.job_id)
    return [func.count().label("edited"),
            func.count().filter(marked_edited).label("marked_edited"),
            func.count().filter(esc).label("escalated")]


def _finish(r: dict) -> dict:
    edited = int(r["edited"] or 0)
    esc = int(r["escalated"] or 0)
    return {"edited": edited, "marked_edited": int(r["marked_edited"] or 0), "escalated": esc, "came_back": esc,
            "clean": edited - esc, "quality_pct": metrics.pct(edited - esc, edited),
            "escalation_free_pct": metrics.pct(edited - esc, edited)}


def quality(db: Session, scope: Scope, by: str = "client") -> dict:
    if by not in ("client", "project"):
        raise ValueError(by)
    sets = metrics.status_sets(db)
    preds = metrics.predicates(scope, sets)
    cols = _columns(preds["edited"])
    base = select().select_from(Form).join(DimProject, DimProject.id == Form.project_id)
    where = [*metrics.dim_conditions(scope), preds["processed"]]

    overall = _finish(dict(db.execute(base.add_columns(*cols).where(*where)).mappings().one()))

    if by == "client":
        q = (base.join(DimClient, DimClient.id == Form.client_id)
             .add_columns(Form.client_id.label("id"), DimClient.name.label("name"), literal(None).label("parent"),
                          *cols).where(*where).group_by(Form.client_id, DimClient.name))
    else:
        q = (base.join(DimClient, DimClient.id == Form.client_id)
             .add_columns(Form.project_id.label("id"), DimProject.name.label("name"),
                          DimClient.name.label("parent"), *cols)
             .where(*where).group_by(Form.project_id, DimProject.name, DimClient.name))
    rows = [{"id": r["id"], "name": r["name"], "parent": r["parent"], **_finish(dict(r))}
            for r in db.execute(q).mappings()]
    rows.sort(key=lambda d: (-d["edited"], str(d["name"])))
    return {"definition": DEFINITION, "overall": overall, "by": by, "rows": rows}
