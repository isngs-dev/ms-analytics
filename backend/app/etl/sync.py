"""Orchestrates one sync run: discover -> classify -> (incrementally) read -> parse -> load."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..models import (AppSetting, ColumnMap, Escalation, Form, Rework, SheetRule, SrcFile, SrcRecord, SrcSheet,
                      SyncIssue, SyncLog)
from .discover import TabRule, classify_tab, is_credential_tab, month_from_tab, parse_workbook_name
from .loader import Loader
from .parse_sheet import AliasIndex, detect_table, parse_sheet
from .sources import FileMeta, SheetSource

# Operational tabs first so forms exist when rework / escalations try to link to them; reference tabs last, because
# a form-like one only adds the Job IDs the main tabs do not have.
_KIND_ORDER = {"master": 0, "operational": 1, "rework": 2, "escalation": 3, "reference": 4}
_READ_KINDS = set(_KIND_ORDER)
_UNCLASSIFIED = TabRule(999, "", "reference", False, True)


def _process_reference(session: Session, loader: Loader, sheet: SrcSheet, rows, parsed, client,
                       alias_index: AliasIndex, previous_kind: str | None, raw_only: bool = False) -> None:
    """A tab no rule counts as data. Judge it by its header and data:
      form-like (Incomplete, Detail..., Copy of ...)  -> supplementary: adds only the Job IDs the main tabs lack
      client-feedback register (Job Id + Feedback)    -> loaded as escalation / feedback rows
      anything else (Data Entry, Updates, e-mails ...) -> every row stored as written, browsable in the app."""
    op = _aliases_for(alias_index, "operational", client.name, parsed.middle)
    esc = _aliases_for(alias_index, "escalation", client.name, parsed.middle)
    detected, ps = (None, None) if raw_only else detect_table(rows, op, esc)
    if detected is not None:
        session.execute(delete(SrcRecord).where(SrcRecord.sheet_id == sheet.id))  # it may have been raw before
        sheet.header = None
        sheet.header_row = ps.header_row
        if detected == "operational":
            sheet.kind = "supplementary"
            loader.process_operational(parsed, ps, client, fill_only=True)
            loader.end_sheet(Form)
        else:
            sheet.kind = "escalation"
            loader.process_escalation(parsed, ps, client)
            loader.end_sheet(Escalation)
        sheet.rows_loaded, sheet.rows_rejected = loader.sheet_loaded, loader.sheet_rejected
        sheet.rows_duplicate = loader.sheet_dups
        sheet.rows_placeholder = max(0, len(rows) - ps.header_row - len(ps.rows)) + loader.sheet_skipped
        return
    stored = loader.store_records(rows)
    sheet.kind = "reference"
    if previous_kind in ("supplementary", "escalation", "operational", "rework"):  # it used to load typed rows
        for model in (Form, Escalation, Rework):
            loader.end_sheet(model)
    sheet.rows_loaded, sheet.rows_rejected, sheet.rows_duplicate = stored, 0, 0
    sheet.rows_placeholder = max(0, len(rows) - stored - (1 if sheet.header else 0))


def _load_rules(session: Session) -> list[TabRule]:
    return [TabRule(r.priority, r.pattern, r.kind, r.include, r.read_cells)
            for r in session.scalars(select(SheetRule))]


def _load_aliases(session: Session) -> AliasIndex:
    return AliasIndex((c.scope, c.scope_ref, f"{c.sheet_kind}:{c.source_header_norm}", c.canonical_field)
                      for c in session.scalars(select(ColumnMap)))


def _aliases_for(index: AliasIndex, kind: str, client: str, project: str | None) -> dict[str, str]:
    merged = index.for_context(client, project)
    prefix = f"{kind}:"
    return {k[len(prefix):]: v for k, v in merged.items() if k.startswith(prefix)}


def run_sync(session: Session, source: SheetSource, trigger: str = "manual", force: bool = False) -> SyncLog:
    log = SyncLog(trigger=trigger, status="running")
    session.add(log)
    session.commit()

    rules = _load_rules(session)
    alias_index = _load_aliases(session)
    had_error = False

    files = list(source.list_files())
    years = sync_years(session)
    if years:  # Admin chose which years to keep: other years leave the analytics and are never read again
        files = [m for m in files if kept_year(m.year, years)]
        _retire_other_years(session, log, years)
    log.files_total = len(files)
    session.commit()

    for meta in files:
        log.files_scanned += 1
        sf = session.scalar(select(SrcFile).where(SrcFile.drive_file_id == meta.drive_file_id))
        if sf is None:
            sf = SrcFile(drive_file_id=meta.drive_file_id, name=meta.name, year=meta.year,
                         quarter=meta.quarter)
            session.add(sf)
            session.flush()
        unchanged = sf.drive_modified_time == meta.modified_time and sf.status == "active"
        if unchanged and not force:
            session.commit()  # persists the scanned counter so progress is visible
            continue
        log.files_changed += 1
        loader = Loader(session, log.id)
        try:
            _process_file(session, source, meta, sf, loader, rules, alias_index, force)
            sf.name, sf.drive_modified_time, sf.status = meta.name, meta.modified_time, "active"
            sf.last_synced_at = datetime.now(timezone.utc)
            log.rows_upserted += loader.rows_upserted
            log.rows_rejected += loader.rows_rejected
            session.commit()
        except Exception as exc:  # one broken workbook must not stop the whole sync
            session.rollback()
            had_error = True
            sf = session.scalar(select(SrcFile).where(SrcFile.drive_file_id == meta.drive_file_id))
            if sf is None:
                sf = SrcFile(drive_file_id=meta.drive_file_id, name=meta.name, year=meta.year,
                             quarter=meta.quarter)
                session.add(sf)
                session.flush()
            sf.status = "error"
            session.add(SyncIssue(sync_id=log.id, severity="error", type="sheet_error", file_id=sf.id,
                                  detail=f"{type(exc).__name__}: {exc}"[:2000]))
            session.commit()

    removed = 0 if had_error else _mark_removed(session, log, {m.drive_file_id for m in files})

    log.finished_at = datetime.now(timezone.utc)
    log.status = "partial" if had_error else "ok"
    # heartbeat: "Drive was checked at ..." even when nothing changed
    hb = session.get(AppSetting, "sync_heartbeat")
    value = {"checked_at": log.finished_at.isoformat(), "files_total": len(files),
             "files_changed": log.files_changed, "status": log.status}
    if hb is None:
        session.add(AppSetting(key="sync_heartbeat", value=value))
    else:
        hb.value = value
    session.commit()
    if trigger == "schedule" and log.files_changed == 0 and removed == 0 and not had_error:
        # a scheduled check that found nothing new is not worth a history row (it would be 144 a day)
        session.delete(log)
        session.commit()
    return log


ONLY_KINDS: set[str] | None = None  # set by scripts/resync_kind.py
SYNC_YEARS_KEY = "sync_years"


def kept_year(year: int | None, years: list[int]) -> bool:
    """A year is kept when it is listed OR newer than every listed year: when a 2027 folder appears in Drive its
    workbooks are picked up by the automatic sync without anyone editing the setting."""
    return year is None or not years or year in years or year > max(years)


def sync_years(session: Session) -> list[int]:
    """Years kept in the analytics (AppSetting 'sync_years' = {"years": [2026]}); empty = every year."""
    row = session.get(AppSetting, SYNC_YEARS_KEY)
    return [int(y) for y in (row.value or {}).get("years", [])] if row else []


def set_sync_years(session: Session, years: list[int]) -> None:
    row = session.get(AppSetting, SYNC_YEARS_KEY)
    if row is None:
        session.add(AppSetting(key=SYNC_YEARS_KEY, value={"years": sorted(years)}))
    else:
        row.value = {"years": sorted(years)}
    session.commit()


def _retire_other_years(session: Session, log: SyncLog, years: list[int]) -> int:
    """Soft-delete the rows of every workbook whose year is not kept (reversible: clear the setting + full re-sync)."""
    other = [f for f in session.scalars(select(SrcFile).where(SrcFile.status != "removed"))
             if not kept_year(f.year, years)]
    _remove_files(session, log, other, f"its year is not in the kept years {sorted(years)}")
    return len(other)


def _mark_removed(session: Session, log: SyncLog, live_ids: set[str]) -> int:
    """Workbooks deleted / moved out of Drive disappear from the analytics too (rows soft-deleted)."""
    known = list(session.scalars(select(SrcFile).where(SrcFile.status != "removed")))
    gone = [f for f in known if f.drive_file_id not in live_ids]
    if not gone:
        return 0
    if len(known) > 10 and len(gone) > 0.5 * len(known):  # a broken listing must not wipe the database
        session.add(SyncIssue(sync_id=log.id, severity="error", type="listing_shrunk",
                              detail=f"{len(gone)} of {len(known)} known workbooks missing from the Drive listing; nothing removed"))
        session.commit()
        return 0
    return _remove_files(session, log, gone, "it is no longer in Drive")


def _remove_files(session: Session, log: SyncLog, gone: list[SrcFile], why: str) -> int:
    now = datetime.now(timezone.utc)
    for f in gone:
        sheet_ids = list(session.scalars(select(SrcSheet.id).where(SrcSheet.file_id == f.id)))
        if sheet_ids:
            for model in (Form, Rework, Escalation):
                session.execute(update(model).where(model.source_sheet_id.in_(sheet_ids), model.deleted_at.is_(None))
                                .values(deleted_at=now))
            session.execute(delete(SrcRecord).where(SrcRecord.sheet_id.in_(sheet_ids)))
            session.execute(update(SrcSheet).where(SrcSheet.id.in_(sheet_ids)).values(content_hash=None))
        f.status = "removed"
        session.add(SyncIssue(sync_id=log.id, severity="info", type="file_removed", file_id=f.id,
                              detail=f"'{f.name}': {why}; its rows were removed from the analytics"))
    session.commit()
    return len(gone)


def _process_file(session, source, meta: FileMeta, sf: SrcFile, loader: Loader,
                  rules: list[TabRule], alias_index: AliasIndex, force: bool):
    parsed = parse_workbook_name(meta.name)
    year = meta.year or parsed.year
    sf.year, sf.quarter = year, meta.quarter or parsed.quarter
    if not parsed.prefix:
        raise ValueError(f"cannot derive a client from file name '{meta.name}'")
    loader.file = sf
    client = loader.client(parsed.prefix)
    sf.client_id, sf.is_multi_project = client.id, parsed.multi
    if parsed.middle and not parsed.multi:
        sf.project_id = loader.project(client, parsed.middle).id

    # Classify every tab. EVERY tab is read except credential tabs, which are never fetched (a hard rule that the
    # admin-editable sheet rules cannot override). A tab no rule counts as data is stored as 'reference'.
    planned: list[tuple[SrcSheet, TabRule]] = []
    prev_kind: dict[int, str] = {}
    raw_only_sheets: set[int] = set()
    for tab in source.list_tabs(meta):
        rule = classify_tab(tab, rules)
        sheet = session.scalar(select(SrcSheet).where(SrcSheet.file_id == sf.id, SrcSheet.tab_name == tab))
        if sheet is None:
            sheet = SrcSheet(file_id=sf.id, tab_name=tab, kind="ignored")
            session.add(sheet)
            session.flush()
        prev_kind[sheet.id] = sheet.kind
        loader.sheet = sheet
        if is_credential_tab(tab):
            sheet.kind, sheet.include = "ignored", False
            continue
        if rule is None:
            rule = _UNCLASSIFIED
            loader.issue("info", "unclassified_tab", f"tab '{tab}' matched no rule; its rows are kept as a reference tab",
                         once=True)
        elif not rule.read_cells:  # switched off by an admin rule
            sheet.kind, sheet.include = "ignored", False
            continue
        elif rule.kind == "client_query":
            rule = TabRule(rule.priority, rule.pattern, "reference", rule.include, rule.read_cells)
        if parsed.is_copy and rule.kind in ("operational", "rework", "escalation"):
            # 'Copy of X' repeats workbook X: its forms may only fill Job IDs X lacks, and its rework / escalation
            # rows are kept as written instead of being counted a second time
            if rule.kind != "operational":
                raw_only_sheets.add(sheet.id)
            rule = TabRule(rule.priority, rule.pattern, "reference", False, True)
        sheet.kind, sheet.include = rule.kind, rule.include
        if rule.kind == "operational":
            sheet.month_start = month_from_tab(tab, year)
        if rule.read_cells and rule.kind in _READ_KINDS:
            planned.append((sheet, rule))

    if ONLY_KINDS:  # a targeted re-read (scripts/resync_kind.py): leave every other tab alone
        planned = [t for t in planned if t[1].kind in ONLY_KINDS]
    planned.sort(key=lambda t: _KIND_ORDER[t[0].kind])
    # one batched read for the whole workbook (Drive: a single round trip), only for tabs we want
    data = source.read_tabs(meta, [s.tab_name for s, _ in planned])
    for sheet, rule in planned:
        loader.begin_sheet(sheet)
        rows = data[sheet.tab_name]
        digest = hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest()
        if sheet.content_hash == digest and not force:
            continue
        sheet.rows_seen = len(rows)
        if rule.kind == "master":
            loader.load_master(rows)  # seeds the error categories...
            stored = loader.store_records(rows)  # ...and every list in it is kept as written too
            sheet.rows_loaded, sheet.rows_rejected, sheet.rows_duplicate = stored, 0, 0
            sheet.rows_placeholder = max(0, len(rows) - stored - (1 if sheet.header else 0))
            sheet.content_hash = digest
            continue
        if rule.kind == "reference":
            _process_reference(session, loader, sheet, rows, parsed, client, alias_index, prev_kind.get(sheet.id),
                               raw_only=sheet.id in raw_only_sheets)
            sheet.content_hash = digest
            continue
        aliases = _aliases_for(alias_index, rule.kind, client.name, parsed.middle)
        ps = parse_sheet(rows, aliases, rule.kind)
        sheet.header_row = ps.header_row
        if ps.header_row is None:
            if rows:
                loader.issue("warn", "sheet_error", f"no header row found in tab '{sheet.tab_name}'")
            sheet.content_hash = digest
            continue
        for h in ps.unmapped_headers:
            loader.issue("info", "unmapped_column", f"'{h}'", once=True)
        for note in ps.notes:  # a header was repaired from the data: say so, it is visible in Data Health
            loader.issue("info", "header_repaired", f"{meta.name} / {sheet.tab_name}: {note}")
        if rule.kind == "operational":
            loader.process_operational(parsed, ps, client)
            loader.end_sheet(Form)
        elif rule.kind == "rework":
            loader.process_rework(parsed, ps, client)
            loader.end_sheet(Rework)
        elif rule.kind == "escalation":
            loader.process_escalation(parsed, ps, client)
            loader.end_sheet(Escalation)
        # reconciliation: every data row in the tab is accounted for
        sheet.rows_loaded, sheet.rows_rejected = loader.sheet_loaded, loader.sheet_rejected
        sheet.rows_duplicate = loader.sheet_dups
        sheet.rows_placeholder = max(0, len(rows) - ps.header_row - len(ps.rows)) + loader.sheet_skipped
        sheet.content_hash = digest

    # QC applicability is detected from data; refresh the flag on projects touched by this file
    session.flush()
