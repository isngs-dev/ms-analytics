"""Global filters -> a resolved Scope used by every endpoint (same semantics everywhere)."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from fastapi import Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AppSetting, Form


@dataclass(frozen=True)
class Scope:
    date_from: date
    date_to: date
    client_ids: tuple[int, ...] = ()
    project_ids: tuple[int, ...] = ()
    editor_id: int | None = None
    qc_member_id: int | None = None
    edit_status: str | None = None
    qc_status: str | None = None
    editor_type: str | None = None

    def with_range(self, a: date, b: date) -> "Scope":
        return replace(self, date_from=a, date_to=b)

    def dims(self) -> dict:
        return {"client_ids": list(self.client_ids), "project_ids": list(self.project_ids),
                "editor_id": self.editor_id, "qc_member_id": self.qc_member_id,
                "edit_status": self.edit_status, "qc_status": self.qc_status,
                "editor_type": self.editor_type}


def iso_week_range(year: int, week: int) -> tuple[date, date]:
    start = date.fromisocalendar(year, week, 1)
    return start, start + timedelta(days=6)


def resolve_period(year=None, quarter=None, month=None, week=None, date_from=None, date_to=None,
                   today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    if date_from or date_to:
        a, b = date_from or date(2000, 1, 1), date_to or today
    elif year and week:
        try:
            a, b = iso_week_range(year, week)
        except ValueError:
            raise HTTPException(422, "invalid ISO week")
    elif year and month:
        a = date(year, month, 1)
        b = a + relativedelta(months=1) - timedelta(days=1)
    elif year and quarter:
        a = date(year, 3 * quarter - 2, 1)
        b = a + relativedelta(months=3) - timedelta(days=1)
    elif year:
        a, b = date(year, 1, 1), date(year, 12, 31)
    else:
        a, b = date(today.year, 1, 1), date(today.year, 12, 31)  # default: the whole current year
    if a > b:
        raise HTTPException(422, "date_from is after date_to")
    return a, b


def window_start(db: Session) -> date | None:
    """1 January of the first kept year (AppSetting 'sync_years'), or None when every year is kept. A kept workbook can
    hold a few rows dated earlier (a 2026 sheet with last year's Input Date): those never open an older year in any
    dropdown or in 'all years'."""
    row = db.get(AppSetting, "sync_years")
    years = [int(y) for y in (row.value or {}).get("years", [])] if row else []
    return date(min(years), 1, 1) if years else None


def data_span(db: Session, today: date | None = None) -> tuple[date, date]:
    """First and last day that has any form activity (received / edited / QC'd); ends no earlier than today."""
    today = today or date.today()
    live = Form.deleted_at.is_(None)
    lo, hi = db.execute(select(
        func.least(func.min(Form.received_date), func.min(Form.edit_date), func.min(Form.qc_date)),
        func.greatest(func.max(Form.received_date), func.max(Form.edit_date), func.max(Form.qc_date))).where(live)).one()
    start = window_start(db)
    if lo is not None and start is not None and lo < start:
        lo = start
    return (lo or today - timedelta(days=364)), max(hi or today, today)


def scope_params(
    period: str | None = Query(None, alias="range", pattern="^all$",
                               description="'all' = every year in the data (ignored when a period or dates are given)"),
    year: int | None = Query(None, ge=2000, le=2100),
    quarter: int | None = Query(None, ge=1, le=4),
    month: int | None = Query(None, ge=1, le=12),
    week: int | None = Query(None, ge=1, le=53),
    date_from: date | None = None,
    date_to: date | None = None,
    client_id: list[int] = Query(default=[]),
    project_id: list[int] = Query(default=[]),
    editor_id: int | None = None,
    qc_member_id: int | None = None,
    edit_status: str | None = None,
    qc_status: str | None = None,
    editor_type: str | None = None,
    db: Session = Depends(get_db),
) -> Scope:
    if period == "all" and not (year or date_from or date_to):
        a, b = data_span(db)
    else:
        a, b = resolve_period(year, quarter, month, week, date_from, date_to)
    return Scope(a, b, tuple(client_id), tuple(project_id), editor_id, qc_member_id, edit_status,
                 qc_status, editor_type)
