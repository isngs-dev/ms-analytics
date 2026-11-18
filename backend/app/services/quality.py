"""Client-feedback quality of the reports that were edited.

Cohort = every report the editors worked on in the selected period: forms with a Transaction Date in the
period, whatever the outcome (Finalized, Edited & Saved, Accepted, Hold ...). This is the `processed` metric.
Counting only the narrow "Edited & Saved" status would leave out most of the work, because the bulk of
edited reports end up as Finalized. How many of them carry the "Edited & Saved" status is reported as
`marked_edited`. Same filters as every other metric. Escalations are counted exactly as the Escalations page counts
them (`escalation_scope.where`: raised in the period, same client / project / editor filters), so the two pages
always show the same number. Rework is not part of any analytics. Quality is the share of edited reports left over:

    quality_pct = (edited - escalations) / edited
"""
from __future__ import annotations

from sqlalchemy import and_, func, literal, select
from sqlalchemy.orm import Session

from ..models import DimClient, DimProject, Escalation, Form
from . import escalation_scope, metrics
from .scope import Scope

DEFINITION = ("Reports edited = every report with a Transaction Date in the period, whatever its final status. "
              "Quality checked = of those reports, in projects that have a QC step, the share with a QC Date by the period end. "
              "Client escalations = the escalations on the Escalations page for the same filters (raised in the period). "
              "Escalation-free = (reports edited - escalations) ÷ reports edited.")


def _columns(marked_edited, qc_scope, qc_done):
    return [metrics.tally().label("edited"), metrics.tally(marked_edited).label("marked_edited"),
            metrics.tally(qc_scope).label("qc_scope"), metrics.tally(qc_scope & qc_done).label("qc_done")]


def _finish(r: dict, escalated: int) -> dict:
    edited = int(r.get("edited") or 0)
    esc = int(escalated or 0)
    clean = max(edited - esc, 0)
    pct = round(100.0 * clean / edited, 2) if edited else None
    scope = int(r.get("qc_scope") or 0)
    done = min(int(r.get("qc_done") or 0), scope)
    return {"edited": edited, "marked_edited": int(r.get("marked_edited") or 0), "escalated": esc, "came_back": esc,
            "clean": clean, "quality_pct": pct, "escalation_free_pct": pct,
            "qc_scope": scope, "qc_done": done, "qc_pending": scope - done,
            "qc_checked_pct": metrics.pct(done, scope)}


def quality(db: Session, scope: Scope, by: str = "client") -> dict:
    if by not in ("client", "project"):
        raise ValueError(by)
    sets = metrics.status_sets(db)
    preds = metrics.predicates(scope, sets)
    # quality check: of the reports edited in the period, in projects that have a QC step, the ones whose QC Date
    # is on or before the period end
    cols = _columns(preds["edited"], metrics.QC_APPLICABLE.is_(True),
                    and_(Form.qc_date.is_not(None), Form.qc_date <= scope.date_to))
    base = select().select_from(Form).join(DimProject, DimProject.id == Form.project_id)
    where = [*metrics.dim_conditions(scope), preds["processed"]]

    # escalations: exactly the rows the Escalations page lists for these filters
    ewhere = escalation_scope.where(scope)
    ekey = Escalation.client_id if by == "client" else Escalation.project_id
    esc_by = {k: int(n) for k, n in db.execute(
        select(ekey, func.count()).where(*ewhere).group_by(ekey))}
    esc_total = sum(esc_by.values())
    overall = _finish(dict(db.execute(base.add_columns(*cols).where(*where)).mappings().one()), esc_total)

    if by == "client":
        q = (base.join(DimClient, DimClient.id == Form.client_id)
             .add_columns(Form.client_id.label("id"), DimClient.name.label("name"), literal(None).label("parent"),
                          *cols).where(*where).group_by(Form.client_id, DimClient.name))
    else:
        q = (base.join(DimClient, DimClient.id == Form.client_id)
             .add_columns(Form.project_id.label("id"), DimProject.name.label("name"),
                          DimClient.name.label("parent"), *cols)
             .where(*where).group_by(Form.project_id, DimProject.name, DimClient.name))
    rows = {r["id"]: {"id": r["id"], "name": r["name"], "parent": r["parent"], **_finish(dict(r), esc_by.get(r["id"], 0))}
            for r in db.execute(q).mappings()}
    missing = [k for k in esc_by if k not in rows]  # escalations of a client / project with nothing edited in the period
    if missing:
        if by == "client":
            names = {i: (n, None) for i, n in db.execute(select(DimClient.id, DimClient.name).where(DimClient.id.in_(missing)))}
        else:
            names = {i: (n, c) for i, n, c in db.execute(
                select(DimProject.id, DimProject.name, DimClient.name).join(DimClient, DimClient.id == DimProject.client_id)
                .where(DimProject.id.in_(missing)))}
        for k in missing:
            if k in names:
                rows[k] = {"id": k, "name": names[k][0], "parent": names[k][1], **_finish({}, esc_by[k])}
    out = sorted(rows.values(), key=lambda d: (-d["edited"], -d["escalated"], str(d["name"])))
    return {"definition": DEFINITION, "overall": overall, "by": by, "rows": out}
