"""Scan EVERY workbook and EVERY tab in the Drive folder and report what the website does / does not load.

For each tab (credential tabs are never read) it records the real header, how many rows carry data, which kind of
table it looks like (operational form tab / rework / escalation-feedback / something else), how the sync classified
it, and - for form-like tabs - how many of its Job IDs are NOT in the database yet.

Run inside the api container:   python scripts/audit_drive.py > /tmp/audit.jsonl
Output: one JSON object per tab (JSON lines) on stdout, progress on stderr.
"""
from __future__ import annotations

import json
import re
import sys

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.etl.drive import DriveSource
from app.etl.normalize import clean_text, norm_header, norm_job_id
from app.etl.parse_sheet import find_header_row, parse_sheet
from app.models import Form, SrcFile, SrcSheet
from app.seed.mapping import ALIASES_BY_KIND

CREDENTIALS = re.compile(r"login|credential|password", re.I)


def aliases(kind: str) -> dict[str, str]:
    return {h: f for f, hs in ALIASES_BY_KIND[kind].items() for h in hs}


def main() -> None:
    src = DriveSource.from_settings(settings)
    al = {k: aliases(k) for k in ("operational", "rework", "escalation")}
    with SessionLocal() as db:
        known_jobs = {j for (j,) in db.execute(select(Form.job_id).where(Form.deleted_at.is_(None)))}
        current = {(f.name, s.tab_name): s.kind for f, s in db.execute(
            select(SrcFile, SrcSheet).join(SrcSheet, SrcSheet.file_id == SrcFile.id))}
    print(f"known job ids: {len(known_jobs)}", file=sys.stderr)

    files = list(src.list_files())
    for n, f in enumerate(files, 1):
        try:
            tabs = [t for t in src.list_tabs(f) if not CREDENTIALS.search(t)]
            data = src.read_tabs(f, tabs) if tabs else {}
        except Exception as exc:  # keep scanning; report the file
            print(json.dumps({"file": f.name, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}), flush=True)
            continue
        for tab in tabs:
            rows = data.get(tab) or []
            rec = {"file": f.name, "tab": tab, "sync_kind": current.get((f.name, tab)), "grid_rows": len(rows)}
            nonblank = [r for r in rows if any(clean_text(c) is not None for c in r)]
            rec["nonblank_rows"] = len(nonblank)
            detected, header_row = "other", None
            for kind in ("operational", "rework", "escalation"):
                h = find_header_row(rows, al[kind], kind)
                if h is not None:
                    detected, header_row = kind, h
                    break
            rec["detected"] = detected
            if detected != "other":
                ps = parse_sheet(rows, al[detected], detected)
                ids = {norm_job_id(r.values.get("job_id")) for r in ps.rows}
                ids.discard(None)
                rec.update(header_row=header_row + 1, real_rows=len(ps.rows), job_ids=len(ids),
                           job_ids_not_in_db=len(ids - known_jobs))
                rec["header"] = [clean_text(c) for c in rows[header_row][:30] if clean_text(c)]
            elif nonblank:
                rec["header"] = [clean_text(c) for c in nonblank[0][:20] if clean_text(c)]
            print(json.dumps(rec, default=str), flush=True)
        if n % 25 == 0:
            print(f"{n}/{len(files)} workbooks", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
