"""Keep only the given years in the analytics (other years' rows are soft-deleted and never synced again).

Run inside the api container:  PYTHONPATH=/app python scripts/keep_years.py 2026
Undo: PYTHONPATH=/app python scripts/keep_years.py all   (then run a full re-sync)
"""
from __future__ import annotations

import sys

from app.config import settings
from app.db import SessionLocal
from app.etl import sync as sync_mod
from app.etl.drive import DriveSource


def main() -> None:
    arg = sys.argv[1:]
    years = [] if arg == ["all"] else [int(a) for a in arg]
    with SessionLocal() as db:
        sync_mod.set_sync_years(db, years)
        print("kept years:", years or "all", flush=True)
        log = sync_mod.run_sync(db, DriveSource.from_settings(settings), "manual", force=False)
        print("sync", log.id, log.status, "files", log.files_scanned, "changed", log.files_changed, flush=True)


if __name__ == "__main__":
    main()
