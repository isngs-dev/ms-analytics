"""Turns parsed sheet rows into canonical rows (forms / rework / escalations) and logs issues."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from ..models import (
    ClientAlias, DimClient, DimErrorCategory, DimPerson, DimProject, Escalation, Form, PersonAlias,
    Rework, SrcFile, SrcRecord, SrcSheet, StatusMap, SyncIssue,
)
from .discover import ParsedName
from .normalize import clean_text, norm_header, norm_job_id, norm_key, parse_date
from .parse_sheet import EXTRA_FIELDS, ParsedSheet, SheetRow


def _hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


# Real sheets contain shifted columns / pasted notes, so a "Job ID" can be a whole sentence and a
# status can be a paragraph. They must never crash a file load (column widths are limited).
_JOB_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_/.#]*$")
MAX_JOB_ID = 40
MIN_DATE = date(2015, 1, 1)  # nothing in this business predates this


def valid_job(job: str | None) -> bool:
    return bool(job) and len(job) <= MAX_JOB_ID and bool(_JOB_OK.match(job))


def _cap(v: str | None, n: int) -> str | None:
    return v if v is None or len(v) <= n else v[:n]


class Loader:
    def __init__(self, session: Session, sync_id: int):
        self.s = session
        self.sync_id = sync_id
        self.now = datetime.now(timezone.utc)
        self.rows_upserted = 0
        self.rows_rejected = 0
        self.file: SrcFile | None = None
        self.sheet: SrcSheet | None = None

        self._status = {(m.field, m.source_value_norm): m for m in session.scalars(select(StatusMap))}
        self._client_alias = {a.alias_norm: a.client_id for a in session.scalars(select(ClientAlias))}
        self._clients = {c.id: c for c in session.scalars(select(DimClient))}
        self._projects = {(p.client_id, p.name.lower()): p for p in session.scalars(select(DimProject))}
        self._person_alias = {a.alias_norm: a.person_id for a in session.scalars(select(PersonAlias))}
        self._error_cats = {c.name.lower(): c.id for c in session.scalars(select(DimErrorCategory))}
        self._once: set[tuple] = set()
        self._forms: dict[int, dict[tuple, Form]] = {}
        self._rework: dict[int, dict[tuple, Rework]] = {}
        self._esc: dict[int, dict[str, Escalation]] = {}
        self._job_index: dict[int, dict[str, int]] = {}
        self._seen_forms: dict[tuple, datetime | None] = {}
        self._sheet_ids: set[int] = set()
        self._sheet_objs: list[Any] = []  # rows touched in this sheet; ids are read after one batched flush
        self._edited_values: set[str] | None = None
        self.sheet_loaded = self.sheet_rejected = self.sheet_dups = self.sheet_skipped = 0  # per-sheet reconciliation
        self.max_date = date.today().replace(year=date.today().year + 1)  # allow a year ahead (scheduled shops)

    def _ok(self) -> None:
        self.rows_upserted += 1
        self.sheet_loaded += 1

    def _rej(self) -> None:
        self.rows_rejected += 1
        self.sheet_rejected += 1

    # ------------------------------------------------------------------ issues
    def issue(self, severity: str, type_: str, detail: str, row_no: int | None = None, once: bool = False):
        if once:
            key = (type_, detail, self.sheet.id if self.sheet else None)
            if key in self._once:
                return
            self._once.add(key)
        self.s.add(SyncIssue(sync_id=self.sync_id, severity=severity, type=type_, detail=detail,
                             file_id=self.file.id if self.file else None,
                             sheet_id=self.sheet.id if self.sheet else None, row_no=row_no))

    # ------------------------------------------------------------------ dimensions
    def client(self, raw: str) -> DimClient:
        name = _cap(clean_text(raw), 128) or "Unknown"
        cid = self._client_alias.get(name.lower())
        if cid is None:
            c = DimClient(name=name)
            self.s.add(c)
            self.s.flush()
            self._clients[c.id] = c
            self._client_alias[name.lower()] = c.id
            self.s.add(ClientAlias(alias_norm=name.lower(), client_id=c.id))
            return c
        return self._clients[cid]

    def project(self, client: DimClient, name: str) -> DimProject:
        name = _cap(clean_text(name), 256) or client.name
        key = (client.id, name.lower())
        p = self._projects.get(key)
        if p is None:
            p = DimProject(client_id=client.id, name=name)
            self.s.add(p)
            self.s.flush()
            self._projects[key] = p
        return p

    def resolve_project(self, client: DimClient, parsed: ParsedName, form_name: str | None) -> DimProject:
        """Level 2: filename middle part; else derived from the Form column (text before ':')."""
        if parsed.middle and not parsed.multi:
            return self.project(client, parsed.middle)
        base = (clean_text(form_name) or "").split(":")[0].strip()
        return self.project(client, base or client.name)

    def person(self, raw: Any) -> int | None:
        name = _cap(clean_text(raw), 128)
        if not name:
            return None
        pid = self._person_alias.get(name.lower())
        if pid is None:
            p = DimPerson(name=name)
            self.s.add(p)
            self.s.flush()
            self._person_alias[name.lower()] = p.id
            self.s.add(PersonAlias(alias_norm=name.lower(), person_id=p.id))
            pid = p.id
        return pid

    def status(self, field: str, raw: Any) -> str | None:
        text = clean_text(raw)
        if not text:
            return None
        m = self._status.get((field, norm_header(text)[:120]))
        if m is None:
            self.issue("warn", "unmapped_status", f"{field}: '{text[:80]}'", once=True)
            return _cap(text, 64)  # kept as-is for the Data Health list, but never wider than the column
        return m.canonical_value

    def counts_as_edited(self, canonical: str | None) -> bool:
        if not canonical:
            return False
        if self._edited_values is None:
            self._edited_values = {m.canonical_value for m in self._status.values() if m.counts_as_edited}
        return canonical in self._edited_values

    def date(self, row: SheetRow, field: str) -> date | None:
        raw = row.values.get(field)
        d = parse_date(raw)
        if d is not None and not (MIN_DATE <= d <= self.max_date):
            # a typo like 2028 or 0204 must not land in the wrong year of the analytics
            self.issue("warn", "bad_date", f"{field}: '{clean_text(raw)}' is outside {MIN_DATE.year}-{self.max_date.year}", row.row_no)
            return None
        if d is None and clean_text(raw):
            self.issue("warn", "bad_date", f"{field}: '{clean_text(raw)}'", row.row_no)
        return d

    def error_category(self, raw: Any) -> int | None:
        name = clean_text(raw)
        return self._error_cats.get(name.lower()) if name else None

    # ------------------------------------------------------------------ master tab
    def load_master(self, rows: list[list[Any]]):
        """Master lists are only used to seed error categories; never counted as forms."""
        for row in rows[:1]:
            for c, cell in enumerate(row):
                if norm_header(cell) in ("errorcategories", "errorcategory"):
                    for r in rows[1:]:
                        name = clean_text(r[c]) if c < len(r) else None
                        if name and name.lower() not in ("all", *self._error_cats):
                            cat = DimErrorCategory(name=name)
                            self.s.add(cat)
                            self.s.flush()
                            self._error_cats[name.lower()] = cat.id

    # ------------------------------------------------------------------ reference tabs (kept as written)
    MAX_RECORD_ROWS = 20_000  # per tab
    MAX_RECORD_COLS = 60
    MAX_CELL_CHARS = 2_000

    @staticmethod
    def _cell_text(v: Any) -> str:
        if isinstance(v, datetime):
            return v.date().isoformat() if (v.hour, v.minute, v.second) == (0, 0, 0) else v.isoformat(sep=" ")
        if isinstance(v, date):
            return v.isoformat()
        if isinstance(v, float) and v.is_integer():
            return str(int(v))  # '4082950.0' -> '4082950'
        return clean_text(v) or ""

    def store_records(self, rows: list[list[Any]]) -> int:
        """Keep every non-blank row of a tab exactly as written (header = first non-blank row). Replaces what a
        previous sync stored for this tab. Returns the number of stored data rows."""
        sheet = self.sheet
        assert sheet is not None
        self.s.execute(delete(SrcRecord).where(SrcRecord.sheet_id == sheet.id))
        sheet.header, sheet.header_row = None, None
        batch: list[dict] = []
        stored = 0
        for idx, raw in enumerate(rows):
            cells = [self._cell_text(c)[: self.MAX_CELL_CHARS] for c in raw[: self.MAX_RECORD_COLS]]
            while cells and not cells[-1]:
                cells.pop()
            if not cells:
                continue
            if sheet.header is None:
                sheet.header, sheet.header_row = cells, idx + 1
                continue
            if stored >= self.MAX_RECORD_ROWS:
                self.issue("warn", "tab_truncated", f"tab '{sheet.tab_name}': only the first {stored} rows are kept", once=True)
                break
            batch.append({"sheet_id": sheet.id, "row_no": idx + 1, "cells": cells})
            stored += 1
            if len(batch) >= 2000:
                self.s.execute(insert(SrcRecord), batch)
                batch = []
        if batch:
            self.s.execute(insert(SrcRecord), batch)
        return stored

    # ------------------------------------------------------------------ caches
    def _forms_for(self, client_id: int) -> dict[tuple, Form]:
        if client_id not in self._forms:
            rows = self.s.scalars(select(Form).where(Form.client_id == client_id))
            self._forms[client_id] = {(f.project_id, f.job_id): f for f in rows}
        return self._forms[client_id]

    def _jobs_for(self, client_id: int) -> dict[str, int]:
        if client_id not in self._job_index:
            idx: dict[str, int] = {}
            for (pid, job) in self._forms_for(client_id):
                idx.setdefault(job, pid)
            self._job_index[client_id] = idx
        return self._job_index[client_id]

    # ------------------------------------------------------------------ operational
    def process_operational(self, parsed: ParsedName, sheet: ParsedSheet, client: DimClient,
                            fill_only: bool = False):
        """fill_only: a supplementary tab (Incomplete, Detail ..., Copy of ...). It may ADD forms the main tabs do
        not have but never changes one that exists, so a stale copy can never overwrite the real row."""
        file_mod = self.file.drive_modified_time if self.file else None
        forms = self._forms_for(client.id)
        this_sheet = self.sheet.id if self.sheet else None
        filled: set[tuple] = set()
        for r in sheet.rows:
            job = norm_job_id(r.values.get("job_id"))
            if not valid_job(job):
                self._rej()
                sev, kind = ("info", "supplementary_skipped") if fill_only else ("error", None)
                if not job:
                    self.issue(sev, kind or "missing_job_id", "row has data but no Shop/Job ID", r.row_no)
                else:  # shifted columns / pasted notes: a sentence is not a Job ID
                    self.issue(sev, kind or "bad_job_id", f"not a Job ID: '{job[:60]}'", r.row_no)
                continue
            project = self.resolve_project(client, parsed, r.values.get("form_name"))
            received = self.date(r, "received_date")
            edit_d = self.date(r, "edit_date")
            qc_d = self.date(r, "qc_date")
            edit_status = self.status("edit_status", r.values.get("edit_status"))
            qc_status = self.status("qc_status", r.values.get("qc_status"))
            editor_id = self.person(r.values.get("editor_name"))
            qc_member_id = self.person(r.values.get("qc_member"))

            if received is None:
                self.issue("warn", "missing_date", f"job {job}: no Input Date", r.row_no)
            if self.counts_as_edited(edit_status) and editor_id is None:
                self.issue("warn", "missing_editor", f"job {job}: edited but no Editor Name", r.row_no)
            if (qc_member_id or qc_d) and not qc_status:
                self.issue("warn", "missing_qc_status", f"job {job}: QC member/date but no QC status",
                           r.row_no)
            if qc_member_id or qc_d:
                project.qc_detected = True

            extra = {k: clean_text(r.values[k]) for k in EXTRA_FIELDS if k in r.values}
            extra.update({k: clean_text(v) for k, v in r.extras.items()})
            if fill_only:
                extra["supplementary_tab"] = self.sheet.tab_name if self.sheet else ""
            values = dict(
                form_name=clean_text(r.values.get("form_name")),
                location=clean_text(r.values.get("location")),
                platform=_cap(clean_text(r.values.get("platform")), 32),
                received_date=received, shop_date=self.date(r, "shop_date"),
                edit_date=edit_d, qc_date=qc_d,
                editor_type=_cap(clean_text(r.values.get("editor_type")), 32),
                editor_id=editor_id, qc_member_id=qc_member_id,
                input_status=self.status("input_status", r.values.get("input_status")),
                edit_status=edit_status, qc_status=qc_status,
                hold_category=clean_text(r.values.get("hold_category")),
                incomplete_status=_cap(clean_text(r.values.get("incomplete_status")), 64),
                client_escalation=clean_text(r.values.get("client_escalation")),
                error_category_raw=_cap(clean_text(r.values.get("error_category_raw")), 128),
                comments_to_shopper=clean_text(r.values.get("comments_to_shopper")),
                qc_feedback=clean_text(r.values.get("qc_feedback")),
                extra={k: v for k, v in extra.items() if v},
            )
            ident = (project.id, job)
            row_hash = _hash(values)
            f = forms.get(ident)
            global_key = (client.id, project.id, job)

            if fill_only:
                if ident in filled or (f is not None and f.source_sheet_id != this_sheet):
                    self.sheet_dups += 1  # already loaded from a main tab (or repeated in this tab): left alone
                    continue
                filled.add(ident)
                if f is None:
                    f = Form(client_id=client.id, project_id=project.id, job_id=job)
                    self.s.add(f)
                    forms[ident] = f
                for k, v in values.items():
                    setattr(f, k, v)
                f.dup_count = 0
                f.source_sheet_id, f.source_row_no, f.row_hash = this_sheet, r.row_no, row_hash
                f.last_seen_at, f.deleted_at = self.now, None
                self._track(f)
                self._ok()
                continue

            repeat = global_key in self._seen_forms  # same identity already seen in this run
            if repeat:
                self.sheet_dups += 1
                self.issue("warn", "duplicate", f"job {job} in {project.name}", r.row_no)
                f.dup_count += 1  # `f` exists: the first sighting created it
                prev_mod = self._seen_forms[global_key]
                if file_mod and prev_mod and file_mod < prev_mod:
                    continue  # the row from the more recently modified file wins
            self._seen_forms[global_key] = file_mod

            if f is None:
                f = Form(client_id=client.id, project_id=project.id, job_id=job)
                self.s.add(f)
                forms[ident] = f
            if not repeat:
                f.dup_count = 0
            for k, v in values.items():
                setattr(f, k, v)
            f.source_sheet_id = self.sheet.id if self.sheet else None
            f.source_row_no = r.row_no
            f.row_hash = row_hash
            f.last_seen_at = self.now
            f.deleted_at = None
            self._track(f)
            self._ok()

    # ------------------------------------------------------------------ rework
    def process_rework(self, parsed: ParsedName, sheet: ParsedSheet, client: DimClient):
        items = []
        for r in sheet.rows:
            job = norm_job_id(r.values.get("job_id"))
            if not valid_job(job):
                self._rej()
                self.issue("error", "missing_job_id" if not job else "bad_job_id",
                           "rework row has no Job ID" if not job else f"not a Job ID: '{job[:60]}'", r.row_no)
                continue
            project = self.resolve_project(client, parsed, r.values.get("form_name"))
            items.append((project, job, self.date(r, "edit_date"), r))
        items.sort(key=lambda t: (t[0].id, t[1], t[2] or date.min, t[3].row_no))

        cache = self._rework.setdefault(
            client.id, {(x.project_id, x.job_id, x.rw_seq): x
                        for x in self.s.scalars(select(Rework).where(Rework.client_id == client.id))})
        forms = self._forms_for(client.id)
        seq: dict[tuple, int] = {}
        for project, job, rw_date, r in items:
            n = seq[(project.id, job)] = seq.get((project.id, job), 0) + 1
            extra = {k: clean_text(r.values[k]) for k in EXTRA_FIELDS if k in r.values}
            extra.update({k: clean_text(v) for k, v in r.extras.items()})
            vals = dict(
                form_name=clean_text(r.values.get("form_name")),
                location=clean_text(r.values.get("location")),
                received_date=self.date(r, "received_date"), shop_date=self.date(r, "shop_date"),
                rw_date=rw_date, editor_type=_cap(clean_text(r.values.get("editor_type")), 32),
                rw_editor_id=self.person(r.values.get("editor_name")),
                rw_status=self.status("edit_status", r.values.get("edit_status")),
                qc_member_id=self.person(r.values.get("qc_member")), qc_date=self.date(r, "qc_date"),
                qc_status=self.status("qc_status", r.values.get("qc_status")),
                feedback=clean_text(r.values.get("qc_feedback")),
                error_category_id=self.error_category(r.values.get("error_category_raw")),
                comments_to_shopper=clean_text(r.values.get("comments_to_shopper")),
                extra={k: v for k, v in extra.items() if v},
            )
            row = cache.get((project.id, job, n))
            if row is None:
                row = Rework(client_id=client.id, project_id=project.id, job_id=job, rw_seq=n)
                self.s.add(row)
                cache[(project.id, job, n)] = row
            for k, v in vals.items():
                setattr(row, k, v)
            linked = forms.get((project.id, job))
            row.form_id = linked.id if linked else None
            row.source_sheet_id = self.sheet.id if self.sheet else None
            row.source_row_no = r.row_no
            row.row_hash = _hash(vals)
            row.deleted_at = None
            self._track(row)
            self._ok()

    # ------------------------------------------------------------------ escalations
    def process_escalation(self, parsed: ParsedName, sheet: ParsedSheet, client: DimClient):
        jobs = self._jobs_for(client.id)
        cache = self._esc.setdefault(
            client.id, {e.row_hash: e for e in self.s.scalars(
                select(Escalation).where(Escalation.client_id == client.id))})
        forms = self._forms_for(client.id)
        for r in sheet.rows:
            job = norm_job_id(r.values.get("job_id"))
            if not valid_job(job):
                job = None  # an escalation may exist without a usable Job ID
            if not job and not (clean_text(r.values.get("client_feedback")) or
                                clean_text(r.values.get("root_cause"))):
                self.sheet_skipped += 1  # an escalation row with nothing in it counts as blank
                continue
            pid = jobs.get(job) if job else None
            if pid is None:
                project = self.project(client, parsed.middle or client.name)
                if job:
                    self.issue("info", "unlinked_escalation",
                               f"job {job}: no matching form; filed under {project.name}", r.row_no)
            else:
                project = next(p for p in self._projects.values() if p.id == pid)
            vals = dict(
                job_id=job, raised_date=self.date(r, "raised_date"),
                editor_type=_cap(clean_text(r.values.get("editor_type")), 32),
                editor_id=self.person(r.values.get("editor_name")),
                qc_member_id=self.person(r.values.get("qc_member")), qc_date=self.date(r, "qc_date"),
                client_feedback=clean_text(r.values.get("client_feedback")),
                root_cause=clean_text(r.values.get("root_cause")),
                preventive_action=clean_text(r.values.get("preventive_action")),
                corrective_action=clean_text(r.values.get("corrective_action")),
                remarks=clean_text(r.values.get("remarks")),
                error_category_id=self.error_category(r.values.get("error_category_raw")),
                extra={k: clean_text(v) for k, v in r.extras.items() if clean_text(v)},
            )
            h = _hash({"client": client.id, "project": project.id, **{
                k: vals[k] for k in ("job_id", "raised_date", "client_feedback", "root_cause")}})
            e = cache.get(h)
            if e is None:
                e = Escalation(client_id=client.id, project_id=project.id, row_hash=h)
                self.s.add(e)
                cache[h] = e
            for k, v in vals.items():
                # actions tracked in the app must not be erased by an empty cell in the sheet
                if v is None and k in ("corrective_action", "preventive_action", "root_cause",
                                       "error_category_id") and getattr(e, k) is not None:
                    continue
                setattr(e, k, v)
            linked = forms.get((project.id, job)) if job else None
            e.form_id = linked.id if linked else None
            e.source_sheet_id = self.sheet.id if self.sheet else None
            e.source_row_no = r.row_no
            e.deleted_at = None
            self._track(e)
            self._ok()

    # ------------------------------------------------------------------ cleanup
    def _track(self, obj: Any) -> None:
        """Rows are flushed in batches (one multi-row INSERT) instead of one round trip per row."""
        self._sheet_objs.append(obj)
        if len(self._sheet_objs) % 1000 == 0:
            self.s.flush()

    def begin_sheet(self, sheet: SrcSheet):
        self.sheet = sheet
        self._sheet_ids = set()
        self._sheet_objs = []
        self.sheet_loaded = self.sheet_rejected = self.sheet_dups = self.sheet_skipped = 0

    def end_sheet(self, model):
        """Soft-delete rows that came from this sheet but are no longer in it."""
        if self.sheet is None:
            return
        self.s.flush()
        self._sheet_ids = {o.id for o in self._sheet_objs}
        ids = set(self.s.scalars(select(model.id).where(
            model.source_sheet_id == self.sheet.id, model.deleted_at.is_(None))))
        stale = ids - self._sheet_ids
        if stale:
            self.s.execute(update(model).where(model.id.in_(stale)).values(deleted_at=self.now))
