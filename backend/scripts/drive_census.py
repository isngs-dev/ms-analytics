"""Count EVERYTHING in the Drive folder by type, and list what the sync does not read (read-only).

Run inside the api container:   PYTHONPATH=/app python scripts/drive_census.py
"""
from __future__ import annotations

from collections import Counter

from app.config import settings
from app.etl.drive import FOLDER_MIME, SHEET_MIME, SHORTCUT_MIME, XLSX_MIME, DriveSource


def main() -> None:
    src = DriveSource.from_settings(settings)
    kinds: Counter = Counter()
    skipped: list[tuple[str, str, str]] = []
    deepest = 0

    def walk(folder_id: str, path: str, depth: int) -> None:
        nonlocal deepest
        deepest = max(deepest, depth)
        for f in src._children(folder_id):
            mime = f["mimeType"]
            if mime == SHORTCUT_MIME and f.get("shortcutDetails"):
                mime = "shortcut->" + f["shortcutDetails"].get("targetMimeType", "?")
            kinds[mime] += 1
            if mime == FOLDER_MIME:
                walk(f["id"], f"{path}/{f['name']}", depth + 1)
            elif mime not in (SHEET_MIME, XLSX_MIME):
                skipped.append((mime, f"{path}/{f['name']}", f["id"]))

    walk(src.root_id, "", 0)
    print("deepest folder level:", deepest)
    for mime, n in kinds.most_common():
        print(f"{n:6d}  {mime}")
    print("--- items that the sync does NOT read:", len(skipped))
    for mime, path, _ in skipped[:40]:
        print(f"  {mime}  {path}")


if __name__ == "__main__":
    main()
