"""Filename / folder / tab discovery rules (pure functions, no I/O)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Protocol

_QUARTER_SUFFIX = re.compile(r"[_\s]+Q([1-4])\s+(\d{4})\s*$", re.I)
_QUARTER_FOLDER = re.compile(r"^Q([1-4])_(\d{4})$", re.I)
_MULTI = re.compile(r"^multi[\s\-_]*projects?$", re.I)
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


@dataclass(frozen=True)
class ParsedName:
    prefix: str  # level 1, e.g. 'HSB', 'CX Orlando'
    middle: str | None  # level 2 from the filename, None when absent
    multi: bool  # 'HSB_Multi-Projects': level 2 must come from the Form column
    quarter: int | None
    year: int | None
    is_copy: bool = False  # 'Copy of X': a duplicate of workbook X, never a client / project of its own


_COPY_PREFIX = re.compile(r"^copy\s+of\s+", re.I)


def parse_workbook_name(name: str) -> ParsedName:
    """'<Prefix>_<Middle>_Q1 2026' with fallbacks for 'CXE_Q1 2026' and 'X_Multi-Projects_Q1 2026'."""
    base = name.strip()
    is_copy = bool(_COPY_PREFIX.match(base))
    base = _COPY_PREFIX.sub("", base)
    q = y = None
    m = _QUARTER_SUFFIX.search(base)
    if m:
        q, y = int(m.group(1)), int(m.group(2))
        base = base[: m.start()]
    prefix, sep, middle = base.partition("_")
    prefix = prefix.strip()
    middle = middle.strip() if sep else ""
    multi = bool(middle and _MULTI.match(middle))
    return ParsedName(prefix=prefix, middle=(middle or None) if not multi else None, multi=multi,
                      quarter=q, year=y, is_copy=is_copy)


def parse_quarter_folder(name: str) -> tuple[int, int] | None:
    m = _QUARTER_FOLDER.match(name.strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def month_from_tab(tab: str, default_year: int | None) -> date | None:
    t = tab.strip().lower()
    for i, mon in enumerate(_MONTHS, start=1):
        if t.startswith(mon):
            y = re.search(r"(\d{4}|\d{2})\s*$", t)
            year = default_year
            if y:
                year = int(y.group(1)) + (2000 if len(y.group(1)) == 2 else 0)
            return date(year, i, 1) if year else None
    return None


CREDENTIAL_TAB = re.compile(r"login|credential|password", re.I)


def is_credential_tab(tab: str) -> bool:
    """Tabs holding logins / passwords are never fetched, whatever the (admin-editable) rules say."""
    return bool(CREDENTIAL_TAB.search(tab))


@dataclass(frozen=True)
class TabRule:
    priority: int
    pattern: str
    kind: str  # operational | rework | escalation | master | client_query | ignored
    include: bool
    read_cells: bool


def classify_tab(tab: str, rules: Iterable[TabRule]) -> TabRule | None:
    """First matching rule (lowest priority number) wins; None means 'no rule matched'."""
    t = tab.strip()
    for r in sorted(rules, key=lambda r: r.priority):
        if re.search(r.pattern, t, re.I):
            return r
    return None
