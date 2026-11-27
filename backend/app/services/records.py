"""Drill-through: the exact rows behind any number, plus search / sort / column chooser / export."""
from __future__ import annotations

import csv
import io
from typing import Iterator

from sqlalchemy import Text, and_, case, cast, func, literal, or_, select
from sqlalchemy.orm import Session, aliased

from ..db import SessionLocal
from ..models import (DimClient, DimErrorCategory, DimPerson, DimProject, Escalation, Form, SrcFile,
                      SrcSheet)
from . import metrics
from .scope import Scope

Editor, Qc = aliased(DimPerson), aliased(DimPerson)

# Where a form is in its life, derived from what the sheet actually holds. The Ops Status / QC Status cells are
# often still blank in the source (e.g. an editor has a Transaction Date but has not marked a status yet), so a
# status column alone would be a wall of dashes for those rows.
STAGE = case(
    (Form.qc_date.is_not(None), "QC done"),
    (Form.edit_date.is_(None), "Waiting for editing"),
    (Form.edit_status.is_(None), "Editing (status not marked yet)"),
    else_=Form.edit_status,
)

FORM_COLUMNS = {
    "id": Form.id, "client": DimClient.name, "project": DimProject.name, "form_name": Form.form_name,
    "job_id": Form.job_id, "location": Form.location, "platform": Form.platform,
    "received_date": Form.received_date, "shop_date": Form.shop_date, "edit_date": Form.edit_date,
    "qc_date": Form.qc_date, "editor_type": Form.editor_type, "editor": Editor.name,
    "qc_member": Qc.name, "input_status": Form.input_status, "edit_status": Form.edit_status,
    "qc_status": Form.qc_status, "hold_category": Form.hold_category,
    "incomplete_status": Form.incomplete_status, "client_escalation": Form.client_escalation,
    "error_category_raw": Form.error_category_raw, "comments_to_shopper": Form.comments_to_shopper,
    "qc_feedback": Form.qc_feedback, "dup_count": Form.dup_count, "units": Form.units,
    # traceability: every record points back to the Drive document, tab and row it came from
    "source_file": SrcFile.name, "source_tab": SrcSheet.tab_name, "source_row": Form.source_row_no,
    "source_file_id": SrcFile.id, "stage": STAGE,
    # filled per request from the selected dates (see _expr): does the form's Input Date fall in the period?
    "received_check": literal(None),
    # every source column that is not part of the standard schema (nothing from the sheet is dropped)
    "other_columns": cast(Form.extra, Text),
}
DEFAULT_FORM_COLUMNS = ["client", "project", "form_name", "job_id", "location", "received_date",
                        "edit_date", "qc_date", "editor", "qc_member", "stage", "edit_status", "qc_status"]
# What is worth showing depends on what is being counted: a form that is pending editing has, by definition,
# no edit date / edit status / QC data yet, so those columns would be empty. Each metric lists the fields that
# are actually filled for its rows (the user can still pick any columns).
_ID = ["client", "project", "form_name", "job_id", "location", "units"]
_SRC = ["source_file", "source_tab", "source_row"]  # row number = the row to look at in the Google Sheet
METRIC_COLUMNS = {
    "received": [*_ID, "shop_date", "received_date", "input_status", "stage", "editor", "editor_type", *_SRC],
    "pending_editing": [*_ID, "shop_date", "received_date", "input_status", "editor", "editor_type",
                        "edit_status", *_SRC],
    "edited": [*_ID, "received_date", "edit_date", "editor", "stage", "edit_status", *_SRC],
    "finalised": [*_ID, "received_date", "received_check", "edit_date", "editor", "stage", "edit_status", *_SRC],
    "processed": [*_ID, "received_date", "received_check", "edit_date", "editor", "stage", "edit_status", "input_status", *_SRC],
    "qc_completed": [*_ID, "edit_date", "qc_date", "editor", "qc_member", "qc_status", "qc_feedback", *_SRC],
    "qc_pending": [*_ID, "received_date", "edit_date", "editor", "edit_status", "qc_member", "qc_status", *_SRC],
}
FORM_METRICS = ["received", "edited", "finalised", "processed", "qc_completed", "pending_editing",
                "qc_pending"]
EXPORT_LIMIT = 200_000
# finalised / processed are counted by Transaction Date, received by Input Date: these two list what separates them
RECONCILED = ("finalised", "processed")


class BadRequest(ValueError):
    pass


def _forms_base(cols):
    return (select(*cols).select_from(Form)
            .join(DimProject, DimProject.id == Form.project_id)
            .join(DimClient, DimClient.id == Form.client_id)
            .outerjoin(Editor, Editor.id == Form.editor_id)
            .outerjoin(Qc, Qc.id == Form.qc_member_id)
            .outerjoin(SrcSheet, SrcSheet.id == Form.source_sheet_id)
            .outerjoin(SrcFile, SrcFile.id == SrcSheet.file_id))


def _form_filters(db: Session, scope: Scope, metric: str | None, search: str | None) -> list:
    where = metrics.dim_conditions(scope)
    if metric:
        if metric not in FORM_METRICS:
            raise BadRequest(f"unknown metric '{metric}'")
        where.append(metrics.predicates(scope, metrics.status_sets(db))[metric])
    if search and search.strip():
        like = f"%{search.strip()}%"
        where.append(or_(Form.job_id.ilike(like), Form.location.ilike(like), Form.form_name.ilike(like),
                         Editor.name.ilike(like), Qc.name.ilike(like), DimProject.name.ilike(like),
                         DimClient.name.ilike(like), SrcFile.name.ilike(like)))
    return where


def _received_in_period(scope: Scope):
    return and_(Form.received_date >= scope.date_from, Form.received_date <= scope.date_to)


def _expr(name: str, scope: Scope):
    """The SQL of a column; 'received_check' depends on the selected dates, so it is built per request."""
    if name == "received_check":
        return case((_received_in_period(scope), "Yes"),
                    (Form.received_date.is_(None), "No – no Input Date"),
                    (Form.received_date < scope.date_from, "No – received before the period"),
                    else_="No – received after the period")
    return FORM_COLUMNS[name]


def _pick_columns(columns: list[str] | None, metric: str | None = None) -> list[str]:
    cols = list(columns or METRIC_COLUMNS.get(metric or "", DEFAULT_FORM_COLUMNS))
    bad = [c for c in cols if c not in FORM_COLUMNS]
    if bad:
        raise BadRequest(f"unknown columns: {', '.join(bad)}")
    if metric in RECONCILED and "received_check" not in cols:
        cols.append("received_check")  # the table highlights the forms that are not part of Received
    return cols


def _order(sort: str | None, order: str, scope: Scope, metric: str | None = None):
    if sort is None:
        first = []
        if metric in RECONCILED:  # the forms that are not in Received come first, so they are never lost on a late page
            first = [case((_received_in_period(scope), 1), else_=0).asc()]
        return [*first, Form.received_date.desc().nulls_last(), Form.id.desc()]
    if sort not in FORM_COLUMNS:
        raise BadRequest(f"unknown sort column '{sort}'")
    col = _expr(sort, scope)
    return [(col.desc() if order == "desc" else col.asc()).nulls_last(), Form.id.asc()]


def reconcile(db: Session, scope: Scope) -> dict:
    """Why Finalised (Transaction Date) and Received (Input Date) differ for the same period, in forms."""
    a, b = scope.date_from, scope.date_to
    p = metrics.predicates(scope, metrics.status_sets(db))
    not_received = or_(Form.received_date.is_(None), Form.received_date < a, Form.received_date > b)
    not_handled = or_(Form.edit_date.is_(None), Form.edit_date < a, Form.edit_date > b)
    handled = p["processed"]
    cols = {
        "finalised": metrics.tally(handled), "received": metrics.tally(p["received"]),
        "no_input_date": metrics.tally(and_(handled, Form.received_date.is_(None))),
        "before": metrics.tally(and_(handled, Form.received_date < a)),
        "after": metrics.tally(and_(handled, Form.received_date > b)),
        "received_not_finalised": metrics.tally(and_(p["received"], not_handled)),
    }
    r = db.execute(_forms_base([v.label(k) for k, v in cols.items()]).where(*metrics.dim_conditions(scope))).mappings().one()
    r = {k: int(v or 0) for k, v in r.items()}
    other = r["no_input_date"] + r["before"] + r["after"]
    return {"finalised": r["finalised"], "received": r["received"], "difference": r["finalised"] - r["received"],
            "not_received": other, "no_input_date": r["no_input_date"], "received_before": r["before"],
            "received_after": r["after"], "received_not_finalised": r["received_not_finalised"]}


def form_records(db: Session, scope: Scope, metric: str | None, search: str | None, sort: str | None,
                 order: str, page: int, page_size: int, columns: list[str] | None) -> dict:
    cols = _pick_columns(columns, metric)
    where = _form_filters(db, scope, metric, search)
    total, units = db.execute(_forms_base([func.count(), func.coalesce(func.sum(Form.units), 0)]).where(*where)).one()
    q = (_forms_base([_expr(c, scope).label(c) for c in cols]).where(*where)
         .order_by(*_order(sort, order, scope, metric)).limit(page_size).offset((page - 1) * page_size))
    rows = [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()}
            for r in db.execute(q).mappings()]
    out = {"total": int(total or 0), "total_units": int(units or 0), "page": page, "page_size": page_size, "columns": cols, "rows": rows,
           "period": {"from": scope.date_from.isoformat(), "to": scope.date_to.isoformat()}}
    if metric in RECONCILED:
        out["reconcile"] = reconcile(db, scope)
    return out


def _export_rows(scope: Scope, metric, search, sort, order, cols) -> Iterator[list]:
    # own session: a streaming response outlives the request-scoped one
    with SessionLocal() as db:
        where = _form_filters(db, scope, metric, search)
        q = (_forms_base([_expr(c, scope).label(c) for c in cols]).where(*where)
             .order_by(*_order(sort, order, scope, metric)).limit(EXPORT_LIMIT)
             .execution_options(yield_per=2000))
        for r in db.execute(q):
            yield [v.isoformat() if hasattr(v, "isoformat") else v for v in r]


def export_prepare(db: Session, scope: Scope, metric, search, sort, order, columns):
    cols = _pick_columns(columns, metric)
    _form_filters(db, scope, metric, search)  # validate early, before streaming starts
    _order(sort, order, scope, metric)
    return cols


def export_csv(scope, metric, search, sort, order, cols) -> Iterator[str]:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    yield buf.getvalue()
    for row in _export_rows(scope, metric, search, sort, order, cols):
        buf.seek(0), buf.truncate()
        w.writerow(["" if v is None else v for v in row])
        yield buf.getvalue()


def export_xlsx(scope, metric, search, sort, order, cols) -> bytes:
    from openpyxl import Workbook

    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Forms")
    ws.append(cols)
    for row in _export_rows(scope, metric, search, sort, order, cols):
        ws.append(list(row))
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
