from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ...db import get_db
from ...services import records as rec
from ...services.scope import Scope, scope_params
from ..deps import manager, viewer

router = APIRouter(prefix="/records", tags=["records"])


def _cols(columns: str | None) -> list[str] | None:
    return [c.strip() for c in columns.split(",") if c.strip()] if columns else None


@router.get("/forms", dependencies=[viewer])
def forms(metric: str | None = Query(None, description=" | ".join(rec.FORM_METRICS)),
          search: str | None = None, sort: str | None = None, order: str = Query("desc", pattern="^(asc|desc)$"),
          page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
          columns: str | None = Query(None, description="comma separated; see /records/columns"),
          scope: Scope = Depends(scope_params), db: Session = Depends(get_db)):
    """The rows behind any number: pass the same filters plus metric=<name> to drill through."""
    try:
        return rec.form_records(db, scope, metric, search, sort, order, page, page_size, _cols(columns))
    except rec.BadRequest as e:
        raise HTTPException(422, str(e))


@router.get("/columns", dependencies=[viewer])
def columns():
    return {"all": list(rec.FORM_COLUMNS), "default": rec.DEFAULT_FORM_COLUMNS,
            "metrics": rec.FORM_METRICS}


@router.get("/forms/export", dependencies=[manager])
def export(format: str = Query("csv", pattern="^(csv|xlsx)$"), metric: str | None = None,
           search: str | None = None, sort: str | None = None, order: str = Query("desc", pattern="^(asc|desc)$"),
           columns: str | None = None, scope: Scope = Depends(scope_params), db: Session = Depends(get_db)):
    try:
        cols = rec.export_prepare(db, scope, metric, search, sort, order, _cols(columns))
    except rec.BadRequest as e:
        raise HTTPException(422, str(e))
    stem = f"forms_{scope.date_from}_{scope.date_to}" + (f"_{metric}" if metric else "")
    if format == "csv":
        return StreamingResponse(rec.export_csv(scope, metric, search, sort, order, cols),
                                 media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{stem}.csv"'})
    data = rec.export_xlsx(scope, metric, search, sort, order, cols)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{stem}.xlsx"'})
