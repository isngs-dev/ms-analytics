"""Verify Google access without loading anything:

    docker compose run --rm api python -m app.etl.drive_check

Prints which credentials are used, the root folder name, how many workbooks were found per
year/quarter, and for the first workbook which tabs the sync would read or skip. It never reads
cell contents and never writes to the database.
"""
from __future__ import annotations

from collections import Counter

from ..config import settings
from .discover import classify_tab, parse_workbook_name, TabRule
from .drive import DriveAccessError, DriveConfigError, DriveSource


def main() -> int:
    try:
        src = DriveSource.from_settings(settings)
    except DriveConfigError as e:
        print(f"NOT CONFIGURED: {e}")
        return 2
    who = src.whoami()
    print(f"credentials : {src.identity}" + (f"  <{who}>" if who else ""))
    try:
        print(f"root folder : {src.root_name()}  ({settings.drive_root_folder_id})")
        files = list(src.list_files())
    except DriveAccessError as e:
        print(f"NO ACCESS   : {e}")
        return 1
    per = Counter((f.year, f.quarter) for f in files)
    print(f"workbooks   : {len(files)}")
    for (y, q), n in sorted(per.items(), key=lambda kv: (kv[0][0] or 0, kv[0][1] or 0)):
        print(f"  {y} Q{q}: {n}")
    if not files:
        print("No workbooks found. Is the folder shared with the account above?")
        return 1

    from sqlalchemy import select
    from ..db import SessionLocal
    from ..models import SheetRule
    with SessionLocal() as db:
        rules = [TabRule(r.priority, r.pattern, r.kind, r.include, r.read_cells) for r in db.scalars(select(SheetRule))]
    first = files[0]
    p = parse_workbook_name(first.name)
    print(f"\nsample      : {first.name}  -> level 1 '{p.prefix}', level 2 '{p.middle or '(from Form column)'}'")
    for tab in src.list_tabs(first):
        r = classify_tab(tab, rules)
        verdict = "NEVER READ" if r and not r.read_cells else (f"read as {r.kind}" if r else "skipped (no rule)")
        print(f"  {tab:<32} {verdict}")
    print("\nOK. Set DATA_SOURCE=drive and SCHEDULER_ENABLED=true in .env to enable auto-sync.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
