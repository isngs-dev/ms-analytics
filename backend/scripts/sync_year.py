"""Force-re-read every workbook of ONE year (e.g. after a parser fix), leaving the other years untouched.

Run inside the api container:  PYTHONPATH=/app python scripts/sync_year.py 2026
Nothing is marked as removed (the listing is filtered, so that check would be wrong).
"""
from __future__ import annotations

import sys

from app.config import settings
from app.db import SessionLocal
from app.etl import sync as sync_mod
from app.etl.drive import DriveSource


class YearSource:
    def __init__(self, inner: DriveSource, year: int):
        self.inner, self.year = inner, year

    def list_files(self):
        return [f for f in self.inner.list_files() if f.year == self.year]

    def __getattr__(self, name):
        return getattr(self.inner, name)


def main() -> None:
    year = int(sys.argv[1])
    sync_mod._mark_removed = lambda *a, **k: 0
    with SessionLocal() as db:
        log = sync_mod.run_sync(db, YearSource(DriveSource.from_settings(settings), year), "manual", force=True)
        print("sync", log.id, log.status, "files", log.files_scanned, "rows", log.rows_upserted,
              "rejected", log.rows_rejected, flush=True)


if __name__ == "__main__":
    main()
