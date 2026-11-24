"""Admin: mapping manager, include/exclude rules, refresh schedule, users, project overrides."""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ... import scheduler
from ...db import get_db
from ...models import (AppSetting, AppUser, ClientAlias, ColumnMap, DimClient, DimProject, PersonAlias,
                       SheetRule, StatusMap, DimPerson)
from ...security import ROLES, hash_password
from ..deps import admin

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[admin])

SHEET_KINDS = ("operational", "rework", "escalation", "master", "client_query", "reference", "ignored")
COLUMN_KINDS = ("operational", "rework", "escalation")
STATUS_FIELDS = ("input_status", "edit_status", "qc_status", "incomplete_status")
CANONICAL_FIELDS = {
    "received_date", "form_name", "location", "job_id", "shop_date", "input_status", "editor_type",
    "editor_name", "edit_date", "edit_status", "comments_to_shopper", "hold_category", "qc_member",
    "qc_date", "qc_status", "qc_feedback", "client_name_raw", "client_escalation", "company_name",
    "error_category_raw", "platform", "incomplete_status", "start_time", "end_time", "submit_datetime",
    "edited_datetime", "raised_date", "client_feedback", "root_cause", "preventive_action",
    "corrective_action", "remarks"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _dump(o, fields) -> dict:
    return {f: getattr(o, f) for f in fields}


# ------------------------------------------------------------------------------ column map
class ColumnMapIn(BaseModel):
    scope: str = Field("global", pattern="^(global|client|project)$")
    scope_ref: str = ""
    sheet_kind: str
    source_header: str  # raw header text; stored normalised
    canonical_field: str
    transform: str | None = None


_CM = ("id", "scope", "scope_ref", "sheet_kind", "source_header_norm", "canonical_field", "transform")


@router.get("/column-map")
def list_column_map(db: Session = Depends(get_db)):
    return [_dump(c, _CM) for c in db.scalars(select(ColumnMap).order_by(
        ColumnMap.sheet_kind, ColumnMap.canonical_field, ColumnMap.source_header_norm))]


@router.post("/column-map", status_code=201)
def add_column_map(body: ColumnMapIn, db: Session = Depends(get_db)):
    if body.sheet_kind not in COLUMN_KINDS:
        raise HTTPException(422, f"sheet_kind must be one of {COLUMN_KINDS}")
    if body.canonical_field not in CANONICAL_FIELDS:
        raise HTTPException(422, "unknown canonical_field")
    n = _norm(body.source_header)
    if not n:
        raise HTTPException(422, "source_header is empty")
    exists = db.scalar(select(ColumnMap.id).where(
        ColumnMap.scope == body.scope, ColumnMap.scope_ref == body.scope_ref,
        ColumnMap.sheet_kind == body.sheet_kind, ColumnMap.source_header_norm == n))
    if exists:
        raise HTTPException(409, "mapping already exists")
    c = ColumnMap(scope=body.scope, scope_ref=body.scope_ref, sheet_kind=body.sheet_kind,
                  source_header_norm=n, canonical_field=body.canonical_field, transform=body.transform)
    db.add(c)
    db.commit()
    return _dump(c, _CM)


@router.delete("/column-map/{id}", status_code=204)
def delete_column_map(id: int, db: Session = Depends(get_db)):
    c = db.get(ColumnMap, id)
    if c is None:
        raise HTTPException(404)
    db.delete(c)
    db.commit()


# ------------------------------------------------------------------------------ status map
class StatusMapIn(BaseModel):
    field: str
    source_value: str
    canonical_value: str
    counts_as_edited: bool = False
    counts_as_finalised: bool = False
    is_hold_or_incomplete: bool = False


_SM = ("id", "field", "source_value_norm", "canonical_value", "counts_as_edited", "counts_as_finalised",
       "is_hold_or_incomplete")


@router.get("/status-map")
def list_status_map(db: Session = Depends(get_db)):
    return [_dump(s, _SM) for s in db.scalars(select(StatusMap).order_by(
        StatusMap.field, StatusMap.canonical_value, StatusMap.source_value_norm))]


@router.put("/status-map")
def upsert_status_map(body: StatusMapIn, db: Session = Depends(get_db)):
    """Create or update. Changing counts_as_edited re-defines 'Edited' for ALL history immediately,
    because metrics read the flags at query time."""
    if body.field not in STATUS_FIELDS:
        raise HTTPException(422, f"field must be one of {STATUS_FIELDS}")
    n = _norm(body.source_value)
    if not n:
        raise HTTPException(422, "source_value is empty")
    s = db.scalar(select(StatusMap).where(StatusMap.field == body.field, StatusMap.source_value_norm == n))
    if s is None:
        s = StatusMap(field=body.field, source_value_norm=n, canonical_value=body.canonical_value)
        db.add(s)
    s.canonical_value = body.canonical_value
    s.counts_as_edited = body.counts_as_edited
    s.counts_as_finalised = body.counts_as_finalised
    s.is_hold_or_incomplete = body.is_hold_or_incomplete
    db.commit()
    return _dump(s, _SM)


@router.delete("/status-map/{id}", status_code=204)
def delete_status_map(id: int, db: Session = Depends(get_db)):
    s = db.get(StatusMap, id)
    if s is None:
        raise HTTPException(404)
    db.delete(s)
    db.commit()


# ------------------------------------------------------------------------------ sheet rules
class SheetRuleIn(BaseModel):
    priority: int
    pattern: str
    kind: str
    include: bool = True
    read_cells: bool = True


_SR = ("id", "priority", "pattern", "kind", "include", "read_cells")


@router.get("/sheet-rules")
def list_rules(db: Session = Depends(get_db)):
    return [_dump(r, _SR) for r in db.scalars(select(SheetRule).order_by(SheetRule.priority))]


def _validate_rule(body: SheetRuleIn):
    if body.kind not in SHEET_KINDS:
        raise HTTPException(422, f"kind must be one of {SHEET_KINDS}")
    try:
        re.compile(body.pattern)
    except re.error as e:
        raise HTTPException(422, f"invalid regex: {e}")


@router.post("/sheet-rules", status_code=201)
def add_rule(body: SheetRuleIn, db: Session = Depends(get_db)):
    _validate_rule(body)
    r = SheetRule(**body.model_dump())
    db.add(r)
    db.commit()
    return _dump(r, _SR)


@router.put("/sheet-rules/{id}")
def update_rule(id: int, body: SheetRuleIn, db: Session = Depends(get_db)):
    _validate_rule(body)
    r = db.get(SheetRule, id)
    if r is None:
        raise HTTPException(404)
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    db.commit()
    return _dump(r, _SR)


@router.delete("/sheet-rules/{id}", status_code=204)
def delete_rule(id: int, db: Session = Depends(get_db)):
    r = db.get(SheetRule, id)
    if r is None:
        raise HTTPException(404)
    db.delete(r)
    db.commit()


# ------------------------------------------------------------------------------ aliases
class AliasIn(BaseModel):
    alias: str
    target_id: int


@router.post("/client-alias", status_code=201)
def add_client_alias(body: AliasIn, db: Session = Depends(get_db)):
    if db.get(DimClient, body.target_id) is None:
        raise HTTPException(422, "unknown client")
    key = body.alias.strip().lower()
    a = db.get(ClientAlias, key)
    if a is None:
        db.add(ClientAlias(alias_norm=key, client_id=body.target_id))
    else:
        a.client_id = body.target_id
    db.commit()
    return {"alias": key, "client_id": body.target_id}


@router.post("/person-alias", status_code=201)
def add_person_alias(body: AliasIn, db: Session = Depends(get_db)):
    if db.get(DimPerson, body.target_id) is None:
        raise HTTPException(422, "unknown person")
    key = body.alias.strip().lower()
    a = db.get(PersonAlias, key)
    if a is None:
        db.add(PersonAlias(alias_norm=key, person_id=body.target_id))
    else:
        a.person_id = body.target_id
    db.commit()
    return {"alias": key, "person_id": body.target_id}


# ------------------------------------------------------------------------------ projects / settings
class ProjectPatch(BaseModel):
    qc_applicable_override: bool | None = None  # null = auto-detect from data


@router.patch("/projects/{project_id}")
def patch_project(project_id: int, body: ProjectPatch, db: Session = Depends(get_db)):
    p = db.get(DimProject, project_id)
    if p is None:
        raise HTTPException(404)
    p.qc_applicable_override = body.qc_applicable_override
    db.commit()
    return {"id": p.id, "qc_applicable_override": p.qc_applicable_override, "qc_detected": p.qc_detected}


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    return {s.key: s.value for s in db.scalars(select(AppSetting))}


@router.put("/settings/{key}")
def put_setting(key: str, value: dict[str, Any], db: Session = Depends(get_db)):
    if key == "refresh_schedule":
        mins = value.get("interval_minutes")
        if not isinstance(mins, int) or not 1 <= mins <= 1440:
            raise HTTPException(422, "interval_minutes must be an integer between 1 and 1440")
    elif key not in ("level_labels",):
        raise HTTPException(404, "unknown setting")
    s = db.get(AppSetting, key)
    if s is None:
        db.add(AppSetting(key=key, value=value))
    else:
        s.value = value
    db.commit()
    rescheduled = scheduler.reschedule(value["interval_minutes"]) if key == "refresh_schedule" else False
    return {"key": key, "value": value, "rescheduled": rescheduled}


# ------------------------------------------------------------------------------ users
class UserIn(BaseModel):
    email: EmailStr
    name: str
    role: str
    password: str = Field(min_length=10)


class UserPatch(BaseModel):
    name: str | None = None
    role: str | None = None
    active: bool | None = None
    password: str | None = Field(None, min_length=10)


def _user(u: AppUser) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "active": u.active,
            "last_login_at": u.last_login_at}


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    return [_user(u) for u in db.scalars(select(AppUser).order_by(AppUser.email))]


@router.post("/users", status_code=201)
def create_user(body: UserIn, db: Session = Depends(get_db)):
    if body.role not in ROLES:
        raise HTTPException(422, f"role must be one of {list(ROLES)}")
    if db.scalar(select(AppUser.id).where(func.lower(AppUser.email) == body.email.lower())):
        raise HTTPException(409, "email already exists")
    u = AppUser(email=body.email.lower(), name=body.name, role=body.role,
                password_hash=hash_password(body.password))
    db.add(u)
    db.commit()
    return _user(u)


@router.patch("/users/{user_id}")
def patch_user(user_id: int, body: UserPatch, me: AppUser = admin, db: Session = Depends(get_db)):
    u = db.get(AppUser, user_id)
    if u is None:
        raise HTTPException(404)
    data = body.model_dump(exclude_unset=True)
    if "role" in data and data["role"] not in ROLES:
        raise HTTPException(422, f"role must be one of {list(ROLES)}")
    if u.id == me.id and (data.get("active") is False or data.get("role", "admin") != "admin"):
        raise HTTPException(422, "you cannot demote or deactivate yourself")
    if "password" in data:
        u.password_hash = hash_password(data.pop("password"))
    for k, v in data.items():
        setattr(u, k, v)
    db.commit()
    return _user(u)
