"""Force-re-read only the tabs of one kind (e.g. escalation tabs after a date-parsing fix), in every kept year.

Run inside the api container:  PYTHONPATH=/app python scripts/resync_kind.py escalation [year ...]
Other tabs are not touched; nothing is marked as removed.
"""
from __future__ import annotations

import sys

from app.config import settings
from app.db import SessionLocal
from app.etl import sync as sync_mod
from app.etl.drive import DriveSource


class YearSource:
    def __init__(self, inner: DriveSource, years: set[int]):
        self.inner, self.years = inner, years

    def list_files(self):
        return [f for f in self.inner.list_files() if not self.years or f.year in self.years]

    def __getattr__(self, name):
        return getattr(self.inner, name)


def main() -> None:
    kind, years = sys.argv[1], {int(y) for y in sys.argv[2:]}
    sync_mod.ONLY_KINDS = {kind}
    sync_mod._mark_removed = lambda *a, **k: 0
    with SessionLocal() as db:
        years = years or set(sync_mod.sync_years(db))
        log = sync_mod.run_sync(db, YearSource(DriveSource.from_settings(settings), years), "manual", force=True)
        print("sync", log.id, log.status, "files", log.files_scanned, "rows", log.rows_upserted,
              "rejected", log.rows_rejected, flush=True)


if __name__ == "__main__":
    main()
