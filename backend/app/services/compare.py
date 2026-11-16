"""Period-over-period comparisons and the alerts derived from them."""
from __future__ import annotations

from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DimClient, DimProject
from . import metrics
from .scope import Scope

MODES = ("week_vs_prev_week", "week_vs_prev_month_week", "month_vs_prev_month",
         "quarter_vs_prev_quarter", "year_vs_prev_year", "custom", "yoy")

# alert thresholds (percent / absolute); kept here so they are easy to expose in Admin later
VOLUME_DROP_PCT = -15.0
VOLUME_MIN_PREV = 20
PENDING_GROWTH_PCT = 25.0
PENDING_MIN_DELTA = 10


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def ranges(mode: str, anchor: date, custom: tuple[date, date] | None = None):
    """((cur_from, cur_to), (prev_from, prev_to)) for a comparison mode."""
    if mode in ("week_vs_prev_week", "week_vs_prev_month_week"):
        a = _monday(anchor)
        cur = (a, a + timedelta(days=6))
        if mode == "week_vs_prev_week":
            p = a - timedelta(days=7)
        else:  # same week one calendar month earlier, snapped back to a Monday
            p = _monday(a - relativedelta(months=1))
        return cur, (p, p + timedelta(days=6))
    if mode == "month_vs_prev_month":
        a = anchor.replace(day=1)
        p = a - relativedelta(months=1)
        return (a, a + relativedelta(months=1, days=-1)), (p, a - timedelta(days=1))
    if mode == "quarter_vs_prev_quarter":
        a = metrics.bucket_start(anchor, "quarter")
        p = a - relativedelta(months=3)
        return (a, a + relativedelta(months=3, days=-1)), (p, a - timedelta(days=1))
    if mode == "year_vs_prev_year":
        a = date(anchor.year, 1, 1)
        p = date(anchor.year - 1, 1, 1)
        return (a, date(anchor.year, 12, 31)), (p, date(anchor.year - 1, 12, 31))
    if mode == "custom" and custom:
        a, b = custom
        n = (b - a).days + 1
        return (a, b), (a - timedelta(days=n), a - timedelta(days=1))
    if mode == "yoy" and custom:  # the selected period against the same dates one year earlier
        a, b = custom
        return (a, b), (a - relativedelta(years=1), b - relativedelta(years=1))
    raise ValueError(mode)


def change(cur: float | int | None, prev: float | int | None) -> dict:
    cur, prev = cur or 0, prev or 0
    pct = None if prev == 0 else round(100.0 * (cur - prev) / prev, 1)
    direction = "flat" if cur == prev else ("up" if cur > prev else "down")
    return {"current": cur, "previous": prev, "delta": cur - prev, "pct_change": pct, "direction": direction}


def compare(db: Session, scope: Scope, mode: str, anchor: date,
            custom: tuple[date, date] | None = None) -> dict:
    (ca, cb), (pa, pb) = ranges(mode, anchor, custom)
    # An unfinished current period is compared like-for-like: only the elapsed days of the
    # previous period are used (otherwise every project would look like a volume collapse).
    today, partial = date.today(), False
    if ca <= today < cb:
        partial = True
        elapsed = (today - ca).days
        cb, pb = today, min(pb, pa + timedelta(days=elapsed))
    cur_s, prev_s = scope.with_range(ca, cb), scope.with_range(pa, pb)
    cur, prev = metrics.overview(db, cur_s), metrics.overview(db, prev_s)
    overall = {k: change(cur[k], prev[k]) for k in metrics.METRICS}

    cur_rows = {r["id"]: r for r in metrics.breakdown(db, cur_s, "project")}
    prev_rows = {r["id"]: r for r in metrics.breakdown(db, prev_s, "project")}
    zero = {m: 0 for m in metrics.METRICS}
    names = {i: (n, cn) for i, n, cn in db.execute(
        select(DimProject.id, DimProject.name, DimClient.name).join(DimClient, DimClient.id == DimProject.client_id))}
    projects, alerts = [], []
    for pid in sorted(set(cur_rows) | set(prev_rows)):
        if pid is None or pid not in names:
            continue
        c, p = cur_rows.get(pid, zero), prev_rows.get(pid, zero)
        shown = ("received", "edited", "qc_completed", "pending_editing", "qc_pending")
        if not any(c[m] or p[m] for m in shown):
            continue  # nothing happened in either period: not worth a row
        row = {"project_id": pid, "project": names[pid][0], "client": names[pid][1],
               **{m: change(c[m], p[m]) for m in ("received", "edited", "qc_completed", "pending_editing",
                                                  "qc_pending")}}
        flags = []
        r = row["received"]
        if r["previous"] >= VOLUME_MIN_PREV and r["pct_change"] is not None and r["pct_change"] <= VOLUME_DROP_PCT:
            flags.append("volume_drop")
        pe = row["pending_editing"]
        if pe["delta"] >= PENDING_MIN_DELTA and (pe["pct_change"] is None or pe["pct_change"] >= PENDING_GROWTH_PCT):
            flags.append("pending_growth")
        row["flags"] = flags
        projects.append(row)
        for f in flags:
            alerts.append({"type": f, "severity": "high" if len(flags) > 1 else "medium",
                           "project_id": pid, "project": row["project"], "client": row["client"],
                           "detail": _alert_text(f, row)})
    projects.sort(key=lambda r: (-len(r["flags"]), -(r["received"]["current"])))
    alerts.sort(key=lambda a: (a["severity"] != "high", a["project"] or ""))
    return {"mode": mode, "partial": partial,
            "thresholds": {"volume_drop_pct": VOLUME_DROP_PCT, "volume_min_previous": VOLUME_MIN_PREV,
                           "pending_growth_pct": PENDING_GROWTH_PCT, "pending_min_delta": PENDING_MIN_DELTA},
            "current": {"from": ca.isoformat(), "to": cb.isoformat()},
            "previous": {"from": pa.isoformat(), "to": pb.isoformat()},
            "overall": overall, "projects": projects, "alerts": alerts}


def _alert_text(flag: str, row: dict) -> str:
    if flag == "volume_drop":
        r = row["received"]
        return f"Incoming volume {r['previous']} -> {r['current']} ({r['pct_change']}%)"
    p = row["pending_editing"]
    return f"Pending editing {p['previous']} -> {p['current']} (+{p['delta']})"
