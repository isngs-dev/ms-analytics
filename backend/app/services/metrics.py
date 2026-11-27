"""Event-based metrics. Every counter uses its OWN date and status, never the form's current state:

  received         Input Date in period
  edited           Transaction Date in period AND Ops Status counts as 'edited' (status_map)
  finalised        every form handled: Transaction Date in period, whatever its Ops Status (same count as processed)
  processed        Transaction Date in period (any outcome, incl. hold / incomplete)
  qc_completed     QC Date in period
  pending_editing  received IN the period, not processed by the period end
  qc_pending       edited IN the period (Edited & Saved), QC-applicable project, QC status not yet changed by the QC member

Only forms of the selected dates are counted: no backlog from earlier months leaks into a period.
The same predicates drive the drill-through (records) endpoints, so a count and its rows always agree.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from dateutil.relativedelta import relativedelta
from sqlalchemy import Date, and_, func, literal, or_, select
from sqlalchemy.orm import Session, aliased

from ..models import DimClient, DimPerson, DimProject, Form, StatusMap
from .scope import Scope

METRICS = ["received", "edited", "finalised", "processed", "qc_completed", "pending_editing",
           "qc_pending"]
DEFINITIONS = {
    "received": "forms whose Input Date falls in the period",
    "edited": "forms whose Transaction Date falls in the period and whose Ops Status counts as edited",
    "finalised": "forms handled in the period: Transaction Date in the period, whatever the Ops Status (Hold, Incomplete, Accepted ... all count)",
    "processed": "forms with a Transaction Date in the period, any outcome",
    "qc_completed": "forms whose QC Date falls in the period",
    "pending_editing": "received in the period and not processed by the period end",
    "qc_pending": "left at Edited & Saved in the period, in a QC-applicable project, and the QC member has not changed the QC Status yet",
    # all three are bounded 0-100%, recomputed for whatever period / filters are selected
    "received_handled": "of the forms received in the period, those already handled (Transaction Date) by the period end",
    "received_pending": "of the forms received in the period, those still not handled at the period end (received_handled + received_pending = received)",
    "editing_pct": "editing workload cleared: processed / (processed + pending editing at period end)",
    "qc_pct": "QC workload cleared: qc_completed / (qc_completed + qc_pending at period end)",
    "completion_pct": "of forms received in the period, the share processed by period end",
    "edited_rate_pct": "edited / received (share of incoming forms that count as 'edited' in the period)",
}


@dataclass(frozen=True)
class StatusSets:
    edited: frozenset[str]
    finalised: frozenset[str]


def status_sets(db: Session) -> StatusSets:
    rows = db.execute(select(StatusMap.canonical_value, StatusMap.counts_as_edited,
                             StatusMap.counts_as_finalised).where(StatusMap.field == "edit_status")).all()
    return StatusSets(frozenset(r[0] for r in rows if r[1]), frozenset(r[0] for r in rows if r[2]))


QC_APPLICABLE = func.coalesce(DimProject.qc_applicable_override, DimProject.qc_detected)


def dim_conditions(scope: Scope) -> list:
    c = [Form.deleted_at.is_(None)]
    if scope.client_ids:
        c.append(Form.client_id.in_(scope.client_ids))
    if scope.project_ids:
        c.append(Form.project_id.in_(scope.project_ids))
    if scope.editor_id is not None:
        c.append(Form.editor_id == scope.editor_id)
    if scope.qc_member_id is not None:
        c.append(Form.qc_member_id == scope.qc_member_id)
    if scope.edit_status:
        c.append(Form.edit_status == scope.edit_status)
    if scope.qc_status:
        c.append(Form.qc_status == scope.qc_status)
    if scope.editor_type:
        c.append(Form.editor_type == scope.editor_type)
    return c


def _qc_untouched(sets: StatusSets):
    """The QC member has not changed the QC Status yet: blank, or still the editor's own "Edited & Saved"."""
    blank = func.coalesce(func.btrim(Form.qc_status), "") == ""
    return or_(blank, Form.qc_status.in_(sets.edited)) if sets.edited else blank


def predicates(scope: Scope, sets: StatusSets) -> dict[str, Any]:
    a, b = scope.date_from, scope.date_to
    edited_ok = Form.edit_status.in_(sets.edited) if sets.edited else literal(False)
    processed = and_(Form.edit_date >= a, Form.edit_date <= b)
    return {
        "received": and_(Form.received_date >= a, Form.received_date <= b),
        "edited": and_(processed, edited_ok),
        "finalised": processed,  # a handled form is finalised: no status is left out, so it lines up with Received
        "processed": processed,
        "qc_completed": and_(Form.qc_date >= a, Form.qc_date <= b),
        # Both "still waiting" numbers belong to the selected dates only (no backlog from earlier months, so the rows
        # behind them and the clients / editors listed are those of the period): received in the period and not handled
        # by its end / handled in the period, in a QC project, and not quality-checked by its end.
        "pending_editing": and_(Form.received_date >= a, Form.received_date <= b,
                                or_(Form.edit_date.is_(None), Form.edit_date > b)),
        # QC pending = the editor left the form at "Edited & Saved" and the QC member has not touched it yet: the QC
        # Status is still blank (or still "Edited & Saved"). As soon as the QC member sets any status (Finalized,
        # Rejected, Completed, Hold ...) it is no longer pending. A QC Date after the period end means it was still
        # waiting at that time.
        "qc_pending": and_(QC_APPLICABLE.is_(True), edited_ok, Form.edit_date >= a, Form.edit_date <= b,
                           or_(and_(Form.qc_date.is_(None), _qc_untouched(sets)), Form.qc_date > b)),
        # cohort: received in the period AND processed by period end
        "cohort_done": and_(Form.received_date >= a, Form.received_date <= b, Form.edit_date.is_not(None),
                            Form.edit_date <= b),
    }


def _form_from():
    return select().select_from(Form).join(DimProject, DimProject.id == Form.project_id)


def pct(a: int | float | None, b: int | float | None) -> float | None:
    if not b:
        return None
    return round(100.0 * (a or 0) / b, 1)


def tally(pred=None):
    """Volume of the rows matching `pred`: the sum of their units. A row is one form, except for the projects counted
    by images (Global Data), where a row carries as many forms as its '#images' cell says."""
    total = func.sum(Form.units)
    return func.coalesce(total.filter(pred) if pred is not None else total, 0)


def _metric_columns(scope: Scope, sets: StatusSets):
    p = predicates(scope, sets)
    cols = [tally(p[m]).label(m) for m in METRICS]
    cols.append(tally(p["cohort_done"]).label("cohort_done"))
    return cols


def _finish(row: dict) -> dict:
    out = {m: int(row[m] or 0) for m in METRICS}
    # Ratios of a flow to a different cohort can exceed 100% (e.g. QC done in May for April's edits), which
    # made the old rings read 100% whatever the filters. These are shares of one workload, so they stay in 0-100.
    out["editing_pct"] = pct(out["processed"], out["processed"] + out["pending_editing"])
    out["qc_pct"] = pct(out["qc_completed"], out["qc_completed"] + out["qc_pending"])
    # what became of the forms received in the period: handled by the period end, or still waiting. The two add up to
    # `received` exactly (unlike pending_editing, which also holds the backlog received before the period).
    out["received_handled"] = min(int(row.get("cohort_done") or 0), out["received"])
    out["received_pending"] = out["received"] - out["received_handled"]
    out["completion_pct"] = pct(row.get("cohort_done"), out["received"])
    out["edited_rate_pct"] = pct(out["edited"], out["received"])
    return out


def overview(db: Session, scope: Scope) -> dict:
    sets = status_sets(db)
    q = _form_from().add_columns(*_metric_columns(scope, sets)).where(*dim_conditions(scope))
    row = db.execute(q).mappings().one()
    out = _finish(dict(row))
    return out


# ------------------------------------------------------------------------------ breakdown
BREAKDOWNS = ("client", "project", "editor", "qc_member", "editor_type", "form")


def breakdown(db: Session, scope: Scope, by: str) -> list[dict]:
    sets = status_sets(db)
    Editor, Qc = aliased(DimPerson), aliased(DimPerson)
    base = _form_from()
    if by == "client":
        base = base.join(DimClient, DimClient.id == Form.client_id)
        key, label, extra = Form.client_id, DimClient.name, literal(None)
    elif by == "project":
        base = base.join(DimClient, DimClient.id == Form.client_id)
        key, label, extra = Form.project_id, DimProject.name, DimClient.name
    elif by == "editor":
        base = base.outerjoin(Editor, Editor.id == Form.editor_id)
        key, label, extra = Form.editor_id, func.coalesce(Editor.name, "(unassigned)"), literal(None)
    elif by == "qc_member":
        base = base.outerjoin(Qc, Qc.id == Form.qc_member_id)
        key, label, extra = Form.qc_member_id, func.coalesce(Qc.name, "(none)"), literal(None)
    elif by == "editor_type":
        key = label = func.coalesce(Form.editor_type, "(unknown)")
        extra = literal(None)
    elif by == "form":
        key = label = func.coalesce(Form.form_name, "(none)")
        extra = literal(None)
    else:
        raise ValueError(by)
    q = (base.add_columns(key.label("key"), label.label("name"), extra.label("parent"),
                          *_metric_columns(scope, sets))
         .where(*dim_conditions(scope)).group_by(key, label, extra))
    out = []
    for r in db.execute(q).mappings():
        d = _finish(dict(r))
        if not any(d[m] for m in METRICS):
            continue
        d.update(id=r["key"] if by not in ("editor_type", "form") else None, name=r["name"],
                 parent=r["parent"])
        out.append(d)
    out.sort(key=lambda d: (-d["received"], -d["processed"], str(d["name"])))
    return out


# ------------------------------------------------------------------------------ time series
GRANULARITIES = ("day", "week", "month", "quarter", "year")


def bucket_start(d: date, g: str) -> date:
    if g == "day":
        return d
    if g == "week":
        return d - timedelta(days=d.weekday())
    if g == "month":
        return d.replace(day=1)
    if g == "quarter":
        return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)
    return date(d.year, 1, 1)


def _next_bucket(d: date, g: str) -> date:
    return {"day": d + timedelta(days=1), "week": d + timedelta(days=7),
            "month": d + relativedelta(months=1), "quarter": d + relativedelta(months=3),
            "year": d + relativedelta(years=1)}[g]


def buckets(a: date, b: date, g: str) -> list[date]:
    out, d = [], bucket_start(a, g)
    while d <= b:
        out.append(d)
        d = _next_bucket(d, g)
    return out


def timeseries(db: Session, scope: Scope, g: str) -> list[dict]:
    sets = status_sets(db)
    p = predicates(scope, sets)
    series = {
        "received": (Form.received_date, p["received"]),
        "edited": (Form.edit_date, p["edited"]),
        "finalised": (Form.edit_date, p["finalised"]),
        "qc_completed": (Form.qc_date, p["qc_completed"]),
    }
    data: dict[date, dict[str, int]] = {d: {m: 0 for m in series} for d in
                                        buckets(scope.date_from, scope.date_to, g)}
    for name, (col, pred) in series.items():
        trunc = func.date_trunc(g, col).cast(Date).label("b")
        q = (_form_from().add_columns(trunc, tally().label("n"))
             .where(*dim_conditions(scope), pred).group_by(trunc))
        for r in db.execute(q):
            data.setdefault(r.b, {m: 0 for m in series})[name] = int(r.n)
    return [{"bucket": d.isoformat(), **v} for d, v in sorted(data.items())]
