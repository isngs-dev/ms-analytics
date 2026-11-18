"""Small, dependency-free cell normalisers shared by the ETL."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

_WS = re.compile(r"\s+")
_MDY = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{2,4})")
_ISO = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_DMY_DASH = re.compile(r"(\d{1,2})[-.](\d{1,2})[-.](\d{2,4})(?!\d)")
_REPEATED_SEP = re.compile(r"([/.\-])\1+")


def norm_header(v: Any) -> str:
    """'Class / Location' -> 'classlocation'; used for headers and status values."""
    return re.sub(r"[^a-z0-9]+", "", str(v if v is not None else "").lower())


def clean_text(v: Any) -> str | None:
    if v is None:
        return None
    s = _WS.sub(" ", str(v).replace("\xa0", " ")).strip()
    return s or None


def norm_key(v: Any) -> str:
    c = clean_text(v)
    return c.lower() if c else ""


def is_blank(v: Any) -> bool:
    return clean_text(v) is None


def parse_date(v: Any, dash_month_first: bool = False) -> date | None:
    """US month-first dates, 2- or 4-digit years, ISO, Sheets serial numbers.

    If a cell holds several dates ('4/24/2025 4/25/2025') the first one wins. Dates with - or . are day-first unless
    `dash_month_first` (a sheet whose own cells prove it: '07-14-26').
    Returns None for blanks and for anything unparseable (caller decides if that is an issue).
    """
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        n = float(v)
        if 20000 < n < 80000:  # Sheets/Excel serial day number
            return date(1899, 12, 30) + timedelta(days=int(n))
        return None
    s = clean_text(v)
    if not s:
        return None
    s = _REPEATED_SEP.sub(r"\1", s)  # '11//11/26' -> '11/11/26'
    d = _DMY_DASH.match(s)  # '13-01-2025' / '13.01.25' / '07-10-26 (' (day first when separated by - or .)
    if d:
        try:
            y = int(d.group(3))
            a, b = int(d.group(1)), int(d.group(2))
            return date(y + 2000 if y < 100 else y, *((a, b) if dash_month_first else (b, a)))
        except ValueError:
            return None
    m = _ISO.search(s)
    try:
        if m and m.start() == 0:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = _MDY.search(s)
        if m:
            a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if y < 100:
                y += 2000
            # the sheets are month-first (US), but a first number above 12 can only be a day: '28/11/2024'
            return date(y, b, a) if a > 12 >= b else date(y, a, b)
    except ValueError:
        return None
    return None


def norm_job_id(v: Any) -> str | None:
    """Shop ID == Job ID. Strips spaces and Sheets' float artefacts ('3318671.0')."""
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    s = clean_text(v)
    if not s:
        return None
    s = s.replace(" ", "")
    if re.fullmatch(r"\d+\.0+", s):
        s = s.split(".")[0]
    return s
