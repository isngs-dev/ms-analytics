"""Locate the header row, map columns to canonical fields, and yield raw row dicts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .normalize import clean_text, norm_header, parse_date

# Columns that are pre-filled on empty template rows; they must not make a row "real".
PREFILL_FIELDS = {"client_name_raw", "error_category_raw", "platform", "company_name"}
# A row that has none of its core fields (ID, dates, people, statuses) is a placeholder, however much
# descriptive text (store, form) or helper-column noise it carries. Such rows are skipped silently
# instead of being reported as "no Job ID": real sheets have tens of thousands of them.
LOW_SIGNAL_FIELDS = PREFILL_FIELDS | {"form_name", "location"}
# Canonical fields that have no dedicated column; they are kept in the `extra` jsonb.
EXTRA_FIELDS = {"company_name", "start_time", "end_time", "submit_datetime", "edited_datetime"}

HEADER_SCAN_ROWS = 15
MIN_HEADER_HITS = {"operational": 5, "rework": 5, "escalation": 4}


@dataclass
class SheetRow:
    row_no: int  # 1-based row number in the source sheet
    values: dict[str, Any]
    extras: dict[str, Any]  # unmapped columns with data, keyed by header text


@dataclass
class ParsedSheet:
    header_row: int | None  # 1-based
    rows: list[SheetRow] = field(default_factory=list)
    unmapped_headers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # header repairs made from the data, shown in Data Health


class AliasIndex:
    """normalised header -> canonical field, with precedence project > client > global."""

    def __init__(self, entries: Iterable[tuple[str, str, str, str]]):
        # entries: (scope, scope_ref, header_norm, canonical_field)
        self._by_scope: dict[tuple[str, str], dict[str, str]] = {}
        for scope, ref, header, canon in entries:
            self._by_scope.setdefault((scope, ref.lower()), {})[header] = canon

    def for_context(self, client: str | None, project: str | None) -> dict[str, str]:
        merged = dict(self._by_scope.get(("global", ""), {}))
        if client:
            merged.update(self._by_scope.get(("client", client.lower()), {}))
        if project:
            merged.update(self._by_scope.get(("project", project.lower()), {}))
        return merged


def find_header_row(rows: Sequence[Sequence[Any]], aliases: dict[str, str], kind: str) -> int | None:
    """0-based index of the best header row in the first rows, or None."""
    need = MIN_HEADER_HITS.get(kind, 5)
    best, best_hits = None, 0
    for i, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        fields = {aliases[n] for n in (norm_header(c) for c in row) if n and n in aliases}
        if len(fields) >= need and len(fields) > best_hits:
            best, best_hits = i, len(fields)
    return best


def map_columns(header: Sequence[Any], aliases: dict[str, str]) -> tuple[list[str | None], list[str]]:
    """Per-column canonical field (or None) plus the list of unmapped non-blank headers.

    Context rules for the messy real-world headers:
    - several columns are literally called 'Status' (input / ops / QC): resolved by the previous
      mapped field (after Shop Date -> input, after Transaction Date -> ops, after QC Date -> QC);
    - a blank header right after QC Date is the QC status column;
    - a blank header in the first column is the Input Date column.
    A field is only assigned once; later duplicates are treated as unmapped.
    """
    status_after = {"shop_date": "input_status", "edit_date": "edit_status", "qc_date": "qc_status"}
    out: list[str | None] = []
    unmapped: list[str] = []
    used: set[str] = set()
    prev: str | None = None
    for i, cell in enumerate(header):
        n = norm_header(cell)
        f: str | None
        if n == "":
            f = "received_date" if i == 0 else ("qc_status" if prev == "qc_date" else None)
        elif n == "status":
            f = status_after.get(prev or "")
        else:
            f = aliases.get(n)
        if f and f in used:
            f = None
        if f:
            used.add(f)
            prev = f
        elif n and n != "status":
            unmapped.append(clean_text(cell) or n)
        out.append(f)
    return out, unmapped


DATE_FIELD = {"operational": "received_date", "rework": "received_date", "escalation": "raised_date"}
DATE_COLUMN_SCAN = 3  # the Input Date column is one of the first three columns of every tab
DATE_SAMPLE_ROWS = 400
MIN_DATE_SHARE = 0.8


def _date_share(rows: Sequence[Sequence[Any]], start: int, col: int) -> tuple[float, int]:
    """Share of the non-blank cells of a column that parse as dates, and how many cells were looked at."""
    seen = hits = 0
    for r in rows[start:start + DATE_SAMPLE_ROWS * 3]:
        if col >= len(r) or clean_text(r[col]) is None:
            continue
        seen += 1
        hits += parse_date(r[col]) is not None
        if seen >= DATE_SAMPLE_ROWS:
            break
    return (hits / seen if seen else 0.0), seen


def infer_date_column(rows: Sequence[Sequence[Any]], h: int, header: Sequence[Any], col_fields: list[str | None],
                      unmapped: list[str], aliases: dict[str, str], kind: str) -> str | None:
    """Real sheets often have a junk header on the Input Date column ('VIEW', 'kya', 'FF', 'n', a second
    'Shop Date' ...) while the cells below are perfectly good dates. When no column was recognised as the
    Input Date, take it from the data: the first of the first three columns that is not already something
    else and whose cells are (almost) all dates. Returns a note describing what was inferred, or None."""
    target = DATE_FIELD.get(kind)
    if target is None or target in col_fields:
        return None

    def take(col: int, note: str) -> str:
        old = col_fields[col]
        col_fields[col] = target
        name = clean_text(header[col]) or norm_header(header[col])
        if old is None and name in unmapped:
            unmapped.remove(name)
        return note.format(name=name or f"column {col + 1}")

    # 'Shop Date' printed twice: the first one (before Form / Shop ID) is the Input Date, the later one is the shop date
    dup = [c for c in range(len(header)) if c > 0 and col_fields[c] is None and norm_header(header[c]) == "shopdate"]
    if dup and col_fields[0] == "shop_date" and _date_share(rows, h + 1, 0)[0] >= MIN_DATE_SHARE:
        note = take(0, "first column '{name}' used as the Input Date (the sheet has two 'Shop Date' columns)")
        col_fields[dup[0]] = "shop_date"
        d = clean_text(header[dup[0]])
        if d in unmapped:
            unmapped.remove(d)
        return note
    for c in range(min(DATE_COLUMN_SCAN, len(header))):
        if col_fields[c] is not None:
            continue
        share, seen = _date_share(rows, h + 1, c)
        if seen >= 3 and share >= MIN_DATE_SHARE:
            return take(c, "column '{name}' used as the Input Date (its header is not a known name but its cells are dates)")
    return None


MIN_JOB_ROWS = 3  # fewer rows with a Job ID than this is a note / template, not a table
MIN_JOB_SHARE = 0.5


def detect_table(rows: Sequence[Sequence[Any]], op_aliases: dict[str, str],
                 esc_aliases: dict[str, str]) -> tuple[str | None, "ParsedSheet | None"]:
    """What kind of table is a tab no rule recognised? Judged by its header AND its data:
    'operational' = a form tab with Input Date / Shop ID / Editor ... columns (Incomplete, Detail..., Copy of ...),
    'escalation'  = a client-feedback register (Job Id / Feedback Details / Error Type / RCA ...),
    None          = anything else (stored as raw rows). A table must carry Job IDs in most of its rows, which keeps
    e-mail templates, instructions and pivots out of the form tables."""
    for kind, aliases in (("operational", op_aliases), ("escalation", esc_aliases)):
        ps = parse_sheet(rows, aliases, kind)
        if ps.header_row is None or len(ps.rows) < MIN_JOB_ROWS:
            continue
        with_job = sum(1 for r in ps.rows if "job_id" in r.values and clean_text(r.values["job_id"]))
        if with_job >= MIN_JOB_ROWS and with_job / len(ps.rows) >= MIN_JOB_SHARE:
            return kind, ps
    return None, None


def parse_sheet(rows: Sequence[Sequence[Any]], aliases: dict[str, str], kind: str) -> ParsedSheet:
    h = find_header_row(rows, aliases, kind)
    if h is None:
        return ParsedSheet(header_row=None)
    header = rows[h]
    col_fields, unmapped = map_columns(header, aliases)
    inferred = infer_date_column(rows, h, header, col_fields, unmapped, aliases, kind)
    out = ParsedSheet(header_row=h + 1, unmapped_headers=unmapped, notes=[inferred] if inferred else [])
    for idx in range(h + 1, len(rows)):
        raw = rows[idx]
        values: dict[str, Any] = {}
        extras: dict[str, Any] = {}
        informative = False
        for c, cell in enumerate(raw):
            if clean_text(cell) is None:
                continue
            f = col_fields[c] if c < len(col_fields) else None
            if f:
                values[f] = cell
                if f not in LOW_SIGNAL_FIELDS:
                    informative = True
            elif c < len(header) and clean_text(header[c]):
                extras[clean_text(header[c]) or str(c)] = cell  # kept, but never makes a row "real"
        if informative:
            out.rows.append(SheetRow(row_no=idx + 1, values=values, extras=extras))
    return out
