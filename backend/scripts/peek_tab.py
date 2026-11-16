"""Show the header row and the first rows of one tab, with the column mapping the loader derives (read-only).

Run inside the api container:  PYTHONPATH=/app python scripts/peek_tab.py "<workbook name>" "<tab>" [rows]
"""
from __future__ import annotations

import sys

from app.config import settings
from app.etl.discover import is_credential_tab
from app.etl.drive import DriveSource
from app.etl.parse_sheet import parse_sheet
from app.seed.mapping import OPERATIONAL_ALIASES

ALIASES = {h: f for f, hs in OPERATIONAL_ALIASES.items() for h in hs}


def main() -> None:
    name, tab = sys.argv[1], sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    if is_credential_tab(tab):
        sys.exit("credential tabs are never read")
    src = DriveSource.from_settings(settings)
    meta = next(f for f in src.list_files() if f.name == name)
    rows = src.read_tab(meta, tab)
    ps = parse_sheet(rows, ALIASES, "operational")
    print("header_row:", ps.header_row, "rows:", len(rows))
    hdr = rows[ps.header_row - 1] if ps.header_row else []
    print("RAW HEADER:", [str(h)[:25] for h in hdr])
    print("UNMAPPED:", ps.unmapped_headers)
    for r in ps.rows[:n]:
        print(r.row_no, {k: (str(v)[:40] if v is not None else None) for k, v in r.values.items()})


if __name__ == "__main__":
    main()
