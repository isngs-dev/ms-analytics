"""Row-by-row, field-by-field parity check: every form tab of every workbook in Drive against the database.

For each data row of each operational tab it finds the database row that came from that exact sheet row
(forms.source_sheet_id + source_row_no) and compares every mapped field with what the cell says.
Rows with no database row are classified: repeat of a Job ID seen earlier (merged), rejected (no / bad Job ID),
or MISSING (a real gap). Output: JSON lines, one summary line per tab and one line per example problem.

Run inside the api container:   PYTHONPATH=/app python scripts/audit_parity.py > /tmp/parity.jsonl
"""
from __future__ import annotations

import json
import sys
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import aliased

from app.config import settings
from app.db import SessionLocal
from app.etl.discover import is_credential_tab
from app.etl.drive import DriveSource
from app.etl.loader import valid_job
from app.etl.normalize import clean_text, norm_header, norm_job_id, parse_date
from app.etl.parse_sheet import parse_sheet
from app.models import DimPerson, Form, SrcFile, SrcSheet, StatusMap
from app.seed.mapping import OPERATIONAL_ALIASES

ALIASES = {h: f for f, hs in OPERATIONAL_ALIASES.items() for h in hs}
DATE_FIELDS = {"received_date": "received_date", "shop_date": "shop_date", "edit_date": "edit_date", "qc_date": "qc_date"}
TEXT_FIELDS = {"form_name": "form_name", "location": "location", "hold_category": "hold_category",
               "comments_to_shopper": "comments_to_shopper", "qc_feedback": "qc_feedback"}
STATUS_FIELDS = {"input_status": "input_status", "edit_status": "edit_status", "qc_status": "qc_status"}
PEOPLE = {"editor_name": "editor_name", "qc_member": "qc_member"}
EXAMPLES_PER_KIND = 6


def main() -> None:
    src = DriveSource.from_settings(settings)
    totals: Counter = Counter()
    examples: dict[str, list] = {}

    def note(kind: str, file: str, tab: str, row: int, detail: str) -> None:
        totals[kind] += 1
        ex = examples.setdefault(kind, [])
        if len(ex) < EXAMPLES_PER_KIND:
            ex.append({"file": file, "tab": tab, "row": row, "detail": detail})

    with SessionLocal() as db:
        status_map = {(m.field, m.source_value_norm): m.canonical_value for m in db.scalars(select(StatusMap))}
        sheets = {(f.name, s.tab_name): s.id for f, s in db.execute(
            select(SrcFile, SrcSheet).join(SrcSheet, SrcSheet.file_id == SrcFile.id).where(SrcSheet.kind == "operational"))}
        client_ids = {f.name: f.client_id for f in db.scalars(select(SrcFile))}
        Ed, Qc = aliased(DimPerson), aliased(DimPerson)
        files = list(src.list_files())
        if len(sys.argv) > 1:  # optional: restrict to one year, e.g. `audit_parity.py 2026`
            files = [f for f in files if f.year == int(sys.argv[1])]
        for n, f in enumerate(files, 1):
            tabs = [t for (name, t) in sheets if name == f.name]
            if not tabs:
                continue
            try:
                data = src.read_tabs(f, tabs)
            except Exception as exc:  # report and continue
                print(json.dumps({"file": f.name, "error": str(exc)[:160]}), flush=True)
                continue
            for tab in tabs:
                rows = data.get(tab) or []
                ps = parse_sheet(rows, ALIASES, "operational")
                if ps.header_row is None:
                    continue
                db_rows = {r.source_row_no: r for r in db.execute(
                    select(Form.source_row_no, Form.job_id, Form.received_date, Form.shop_date, Form.edit_date, Form.qc_date,
                           Form.form_name, Form.location, Form.hold_category, Form.comments_to_shopper, Form.qc_feedback,
                           Form.input_status, Form.edit_status, Form.qc_status, Ed.name.label("editor_name"),
                           Qc.name.label("qc_member"), Form.deleted_at)
                    .outerjoin(Ed, Ed.id == Form.editor_id).outerjoin(Qc, Qc.id == Form.qc_member_id)
                    .where(Form.source_sheet_id == sheets[(f.name, tab)]))}
                tab_stat: Counter = Counter()
                seen_jobs: set[str] = set()
                for r in ps.rows:
                    job = norm_job_id(r.values.get("job_id"))
                    tab_stat["rows"] += 1
                    d = db_rows.get(r.row_no)
                    if d is None or d.deleted_at is not None or d.job_id != job:
                        if not valid_job(job):
                            tab_stat["rejected_job"] += 1
                            note("rejected_bad_or_missing_job_id", f.name, tab, r.row_no, str(job))
                        elif job in seen_jobs:
                            tab_stat["merged_repeat"] += 1
                        elif db.scalar(select(Form.id).where(
                                Form.job_id == job, Form.client_id == client_ids[f.name],
                                Form.deleted_at.is_(None)).limit(1)) is not None:
                            # the same client + Job ID is loaded from another workbook / tab (a copied tab): one form
                            tab_stat["same_job_loaded_elsewhere"] += 1
                        else:
                            tab_stat["missing"] += 1
                            note("MISSING_row_not_in_database", f.name, tab, r.row_no, str(job))
                        seen_jobs.add(job or "")
                        continue
                    seen_jobs.add(job)
                    tab_stat["matched"] += 1
                    for src_f, col in DATE_FIELDS.items():
                        raw = r.values.get(src_f)
                        want, have = parse_date(raw), getattr(d, col)
                        if want is None and clean_text(raw):
                            note(f"date_unparseable[{src_f}]", f.name, tab, r.row_no, repr(clean_text(raw))[:40])
                        elif want is not None and have is None:
                            note(f"LOST_date[{src_f}]", f.name, tab, r.row_no, f"{raw!r}")
                        elif want is not None and have != want:
                            note(f"CHANGED_date[{src_f}]", f.name, tab, r.row_no, f"{raw!r} -> {have}")
                    for src_f, col in TEXT_FIELDS.items():
                        want, have = clean_text(r.values.get(src_f)), getattr(d, col)
                        if want and not have:
                            note(f"LOST_text[{src_f}]", f.name, tab, r.row_no, want[:40])
                        elif want and have and want != have:
                            note(f"CHANGED_text[{src_f}]", f.name, tab, r.row_no, f"{want[:30]} -> {have[:30]}")
                    for src_f, col in STATUS_FIELDS.items():
                        want, have = clean_text(r.values.get(src_f)), getattr(d, col)
                        if want and not have:
                            note(f"LOST_status[{src_f}]", f.name, tab, r.row_no, want[:40])
                        elif want and have and norm_header(want)[:120] != norm_header(have) \
                                and status_map.get((src_f, norm_header(want)[:120])) != have:
                            note(f"CHANGED_status[{src_f}]", f.name, tab, r.row_no, f"{want[:30]} -> {have[:30]}")
                    for src_f, col in PEOPLE.items():
                        want, have = clean_text(r.values.get(src_f)), getattr(d, col)
                        if want and not have:
                            note(f"LOST_person[{src_f}]", f.name, tab, r.row_no, want[:40])
                print(json.dumps({"file": f.name, "tab": tab, **tab_stat}), flush=True)
            if n % 25 == 0:
                print(f"{n}/{len(files)} workbooks", file=sys.stderr, flush=True)

    print(json.dumps({"TOTALS": dict(totals), "EXAMPLES": examples}, default=str), flush=True)


if __name__ == "__main__":
    main()
