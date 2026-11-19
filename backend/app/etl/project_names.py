"""Project (level 2) naming rules, shared by the loader and the data fix-up.

* One canonical key per project: names that differ only in case / spacing / punctuation
  ('EWR - Retail Shop' / 'EWR- Retail Shop', 'Drai's' / 'Drais') are the same project.
* Rows whose sheet left the Form column empty are filed under '<Client> (form missing in sheet)', never under a project
  named after the client (that looked like a real project called 'CXE' inside client 'CXE').
"""
from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.orm import Session, aliased

from ..models import DimClient, DimProject, Escalation, Form, Rework, SnapshotMonthly, SrcFile

UNNAMED_SUFFIX = " (form missing in sheet)"


def norm_project(name: str) -> str:
    """Key under which spelling variants of one project collapse (letters and digits only, case-folded)."""
    low = (name or "").lower()
    return re.sub(r"[\W_]+", "", low) or low.strip()


def unnamed_project_name(client_name: str) -> str:
    return f"{client_name}{UNNAMED_SUFFIX}"


def _has_named_form(session: Session, project_id: int) -> bool:
    return bool(session.scalar(
        select(func.count()).select_from(Form)
        .where(Form.project_id == project_id, func.nullif(func.trim(Form.form_name), "").is_not(None))))


def _clear_retired_duplicates(session: Session, other: int, keep: int) -> None:
    """A live row of `other` may share its job id with a soft-deleted row (an older, retired workbook) already in `keep`.
    The unique key allows one of them, and the live one is the truth: drop the retired tombstone (and what pointed at
    it) so the live row can move."""
    live = aliased(Form)
    dead = select(Form.id).where(Form.project_id == keep, Form.deleted_at.is_not(None), exists().where(
        live.project_id == other, live.deleted_at.is_(None), live.client_id == Form.client_id,
        live.job_id == Form.job_id))
    session.execute(update(Rework).where(Rework.form_id.in_(dead)).values(form_id=None))
    session.execute(update(Escalation).where(Escalation.form_id.in_(dead)).values(form_id=None))
    session.execute(delete(Form).where(Form.id.in_(dead)))
    # and the other way round: a retired row of `other` that already has a twin in `keep` is just dropped
    twin = aliased(Form)
    stale = select(Form.id).where(Form.project_id == other, Form.deleted_at.is_not(None), exists().where(
        twin.project_id == keep, twin.client_id == Form.client_id, twin.job_id == Form.job_id))
    session.execute(update(Rework).where(Rework.form_id.in_(stale)).values(form_id=None))
    session.execute(update(Escalation).where(Escalation.form_id.in_(stale)).values(form_id=None))
    session.execute(delete(Form).where(Form.id.in_(stale)))


def _move_rows(session: Session, other: int, keep: int) -> None:
    """Re-point everything of project `other` to `keep`, except rows that would collide with one already there."""
    _clear_retired_duplicates(session, other, keep)
    f2 = aliased(Form)
    session.execute(update(Form).where(Form.project_id == other, ~exists().where(
        f2.project_id == keep, f2.client_id == Form.client_id, f2.job_id == Form.job_id)).values(project_id=keep))
    r2 = aliased(Rework)
    session.execute(update(Rework).where(Rework.project_id == other, ~exists().where(
        r2.project_id == keep, r2.client_id == Rework.client_id, r2.job_id == Rework.job_id,
        r2.rw_seq == Rework.rw_seq)).values(project_id=keep))
    session.execute(update(Escalation).where(Escalation.project_id == other).values(project_id=keep))
    session.execute(update(SrcFile).where(SrcFile.project_id == other).values(project_id=keep))
    session.execute(delete(SnapshotMonthly).where(SnapshotMonthly.project_id == other))  # derived, rebuilt on demand


def _still_used(session: Session, project_id: int) -> bool:
    return any(session.scalar(select(func.count()).select_from(m).where(m.project_id == project_id))
               for m in (Form, Rework, Escalation, SrcFile))


def fix_project_names(session: Session) -> dict[str, int]:
    """Rename 'project == client' placeholders and merge spelling variants into the project with the most forms.
    Idempotent; a form that exists under both spellings (same job id) is left where it is, never overwritten."""
    renamed = merged = 0
    clients = {c.id: c.name for c in session.scalars(select(DimClient))}
    taken = {(p.client_id, p.name) for p in session.scalars(select(DimProject))}
    for p in session.scalars(select(DimProject).order_by(DimProject.id)).all():
        cname = clients.get(p.client_id)
        if not cname or p.name.lower() != cname.lower():
            continue
        new = unnamed_project_name(cname)
        if (p.client_id, new) in taken or _has_named_form(session, p.id):
            continue
        taken.discard((p.client_id, p.name))
        p.name = new
        taken.add((p.client_id, new))
        renamed += 1
    session.flush()

    counts = dict(session.execute(select(Form.project_id, func.count()).group_by(Form.project_id)).all())
    groups: dict[tuple[int, str], list[DimProject]] = defaultdict(list)
    for p in session.scalars(select(DimProject).order_by(DimProject.id)):
        groups[(p.client_id, norm_project(p.name))].append(p)
    for variants in groups.values():
        if len(variants) < 2:
            continue
        keep = max(variants, key=lambda p: (counts.get(p.id, 0), -p.id))
        # the name people see: the readable spelling (a Drive file name turns ':' '/' "'" into '_'), then the biggest
        display = min(variants, key=lambda p: (p.name.count("_"), -counts.get(p.id, 0), p.id)).name
        gone = 0
        for other in variants:
            if other is keep:
                continue
            _move_rows(session, other.id, keep.id)
            session.flush()
            if not _still_used(session, other.id):
                session.delete(other)
                gone += 1
        merged += gone
        session.flush()
        if gone and display != keep.name:
            keep.name = display
    session.flush()
    return {"renamed": renamed, "merged": merged}
