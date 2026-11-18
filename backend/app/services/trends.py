"""Overall-page analytics that follow the global filters:

  forms_compare   every form (form_name) inside every project, this period against the previous period / last year
  month_drivers   month by month: did the volume go down, and which project's forms made it go down

Both reuse the event-based predicates of `metrics`, so a count here equals the same count anywhere else.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from sqlalchemy import Date, func, select
from sqlalchemy.orm import Session

from ..models import DimClient, DimProject, Form
from . import compare, metrics
from .scope import Scope

COMPARED = ("received", "edited", "qc_completed", "pending_editing")
# the date column a counted metric is bucketed by
METRIC_DATE = {"received": Form.received_date, "edited": Form.edit_date, "finalised": Form.edit_date,
               "processed": Form.edit_date, "qc_completed": Form.qc_date}
DROP_METRICS = tuple(METRIC_DATE)
NO_FORM = "(no form name)"
MAX_DECLINERS, MAX_GAINERS, MAX_FORMS = 10, 5, 6


def _form_label():
    return func.coalesce(func.nullif(func.trim(Form.form_name), ""), NO_FORM)


def _by_project_form(db: Session, scope: Scope) -> dict[tuple[int, str], dict]:
    sets = metrics.status_sets(db)
    label = _form_label()
    q = (metrics._form_from().add_columns(Form.project_id.label("pid"), label.label("form"),
                                          *metrics._metric_columns(scope, sets))
         .where(*metrics.dim_conditions(scope)).group_by(Form.project_id, label))
    return {(r["pid"], r["form"]): {m: int(r[m] or 0) for m in metrics.METRICS} for r in db.execute(q).mappings()}


def _names(db: Session) -> dict[int, tuple[str, str]]:
    return {i: (n, c) for i, n, c in db.execute(
        select(DimProject.id, DimProject.name, DimClient.name).join(DimClient, DimClient.id == DimProject.client_id))}


# ------------------------------------------------------------------------------ the forms behind any change (hover)
def change_drivers(db: Session, scope: Scope, metric: str, cur: tuple[date, date], prev: tuple[date, date],
                   limit: int = 8) -> dict:
    """Which forms (project + form name) made `metric` go up or down between two periods. The ranges are the very
    ones a comparison cell used, so the deltas of the forms add up to the change the cell shows."""
    if metric not in metrics.METRICS:
        raise ValueError(metric)
    c = _by_project_form(db, scope.with_range(*cur))
    p = _by_project_form(db, scope.with_range(*prev))
    names = _names(db)
    rows = []
    for key in set(c) | set(p):
        pid, form = key
        if pid not in names:
            continue
        now, before = c.get(key, {}).get(metric, 0), p.get(key, {}).get(metric, 0)
        if now != before:
            rows.append({"project_id": pid, "project": names[pid][0], "client": names[pid][1], "form": form,
                         "current": now, "previous": before, "delta": now - before})
    down = sorted((r for r in rows if r["delta"] < 0), key=lambda r: (r["delta"], r["project"], r["form"]))
    up = sorted((r for r in rows if r["delta"] > 0), key=lambda r: (-r["delta"], r["project"], r["form"]))
    tot_c = sum(v.get(metric, 0) for (pid, _), v in c.items() if pid in names)
    tot_p = sum(v.get(metric, 0) for (pid, _), v in p.items() if pid in names)
    return {"metric": metric, "definition": metrics.DEFINITIONS[metric],
            "current": {"from": cur[0].isoformat(), "to": cur[1].isoformat(), "total": tot_c},
            "previous": {"from": prev[0].isoformat(), "to": prev[1].isoformat(), "total": tot_p},
            "delta": tot_c - tot_p,
            "decliners": down[:limit], "decliner_count": len(down), "decline_total": sum(r["delta"] for r in down),
            "gainers": up[:limit], "gainer_count": len(up), "gain_total": sum(r["delta"] for r in up)}


# ------------------------------------------------------------------------------ forms inside projects
def forms_compare(db: Session, scope: Scope, vs: str = "previous", today: date | None = None) -> dict:
    today = today or date.today()
    mode = "yoy" if vs == "yoy" else "custom"
    (ca, cb), (pa, pb) = compare.ranges(mode, scope.date_from, (scope.date_from, scope.date_to))
    partial = False
    if ca <= today < cb:  # an unfinished period is compared like-for-like (only the elapsed days of the other one)
        partial = True
        cb, pb = today, min(pb, pa + timedelta(days=(today - ca).days))
    cur = _by_project_form(db, scope.with_range(ca, cb))
    prev = _by_project_form(db, scope.with_range(pa, pb))
    names = _names(db)
    zero = {m: 0 for m in metrics.METRICS}

    projects: dict[int, dict] = {}
    for key in set(cur) | set(prev):
        pid, form = key
        if pid not in names:
            continue
        c, p = cur.get(key, zero), prev.get(key, zero)
        if not any(c[m] or p[m] for m in COMPARED):
            continue
        row = {"form": form, **{m: compare.change(c[m], p[m]) for m in COMPARED}}
        proj = projects.setdefault(pid, {"project_id": pid, "project": names[pid][0], "client": names[pid][1],
                                         "forms": [], "_c": defaultdict(int), "_p": defaultdict(int)})
        proj["forms"].append(row)
        for m in COMPARED:
            proj["_c"][m] += c[m]
            proj["_p"][m] += p[m]
    out = []
    for proj in projects.values():
        c, p = proj.pop("_c"), proj.pop("_p")
        proj.update({m: compare.change(c[m], p[m]) for m in COMPARED})
        proj["forms"].sort(key=lambda r: (-r["received"]["current"], -r["received"]["previous"], r["form"]))
        proj["form_count"] = len(proj["forms"])
        out.append(proj)
    out.sort(key=lambda r: (-r["received"]["current"], -r["received"]["previous"], r["project"]))
    return {"vs": vs, "partial": partial, "current": {"from": ca.isoformat(), "to": cb.isoformat()},
            "previous": {"from": pa.isoformat(), "to": pb.isoformat()}, "projects": out,
            "definition": "Each form name is counted with the same rules as every other number: received = Input Date "
                          "in the period, edited = Transaction Date in the period with an edited status, QC = QC Date; "
                          "pending is as of the period end."}


# ------------------------------------------------------------------------------ forms month by month (whole-year view)
def _months_in(scope: Scope, today: date) -> list[date]:
    months, d = [], scope.date_from.replace(day=1)
    while d <= scope.date_to and d <= today:
        months.append(d)
        d += relativedelta(months=1)
    return months


def forms_by_month(db: Session, scope: Scope, metric: str = "received", today: date | None = None) -> dict:
    """Every form of every project, one column per calendar month of the selected period (a year, a quarter, any range),
    so a whole year can be compared month against month even when the year before is not loaded."""
    if metric not in METRIC_DATE:
        raise ValueError(metric)
    today = today or date.today()
    months = _months_in(scope, today)
    out = {"metric": metric, "definition": metrics.DEFINITIONS[metric], "months": [m.isoformat() for m in months],
           "partial_month": None, "totals": [], "projects": []}
    if not months:
        return out
    if months[-1] <= today < _month_end(months[-1]):
        out["partial_month"] = months[-1].isoformat()
    counts = _month_counts(db, scope.with_range(months[0], min(_month_end(months[-1]), today)), metric)
    index = {m: i for i, m in enumerate(months)}
    names = _names(db)
    projects: dict[int, dict] = {}
    totals = [0] * len(months)
    for (m, pid, form), n in counts.items():
        if m not in index or pid not in names:
            continue
        i = index[m]
        totals[i] += n
        proj = projects.setdefault(pid, {"project_id": pid, "project": names[pid][0], "client": names[pid][1],
                                         "months": [0] * len(months), "forms": {}})
        proj["months"][i] += n
        proj["forms"].setdefault(form, [0] * len(months))[i] += n
    rows = []
    for proj in projects.values():
        forms = [{"form": f, "months": v, "total": sum(v)} for f, v in proj["forms"].items()]
        forms.sort(key=lambda r: (-r["total"], r["form"]))
        rows.append({**proj, "forms": forms, "form_count": len(forms), "total": sum(proj["months"])})
    rows.sort(key=lambda r: (-r["total"], r["project"]))
    out.update(totals=totals, projects=rows)
    return out


# ------------------------------------------------------------------------------ Monday-Sunday weeks, week n of every month
WEEK_METRICS = ("received", "edited", "finalised", "qc_completed")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def month_weeks(month: date) -> list[date]:
    """Mondays of the whole Monday-Sunday weeks that belong to a month. A week belongs to the month that holds its
    Thursday (the ISO rule), so every week is complete, no day is counted twice and each week sits in one month."""
    first = month.replace(day=1)
    last = _month_end(first)
    thu = first + timedelta(days=(3 - first.weekday()) % 7)
    out = []
    while thu <= last:
        out.append(thu - timedelta(days=3))
        thu += timedelta(days=7)
    return out


def _day_counts(db: Session, scope: Scope, metric: str) -> dict[date, int]:
    sets = metrics.status_sets(db)
    pred = metrics.predicates(scope, sets)[metric]
    col = METRIC_DATE[metric]
    q = (metrics._form_from().add_columns(col.label("d"), metrics.tally().label("n"))
         .where(*metrics.dim_conditions(scope), pred).group_by(col))
    return {r["d"]: int(r["n"]) for r in db.execute(q).mappings() if r["d"] is not None}


def _span(daily: dict[date, int], a: date, b: date) -> int:
    return sum(daily.get(a + timedelta(days=i), 0) for i in range((b - a).days + 1))


def week_grid(db: Session, scope: Scope, metric: str = "received", today: date | None = None) -> dict:
    """Monday-Sunday weeks of every month in the selected period, one cell per day (a Sunday with no work is a 0,
    not a gap), each week against the previous week and against the same week number of the month before.
    The week still running is compared with the same number of days of the other week. Ranges of every comparison
    are returned, so a hover can ask `change_drivers` which forms moved the number."""
    if metric not in WEEK_METRICS:
        raise ValueError(metric)
    today = today or date.today()
    months, d = [], scope.date_from.replace(day=1)
    while d <= scope.date_to and d <= today:
        months.append(d)
        d += relativedelta(months=1)

    layout: list[tuple[date, list[date], list[date]]] = []  # month, its shown Mondays, the month before's Mondays
    for m in months:
        shown = [mon for mon in month_weeks(m)
                 if mon <= today and mon <= scope.date_to and mon + timedelta(days=6) >= scope.date_from]
        if shown:
            layout.append((m, shown, month_weeks(m - relativedelta(months=1))))
    base = {"metric": metric, "definition": metrics.DEFINITIONS[metric], "weekdays": list(WEEKDAYS),
            "rule": "Weeks run Monday to Sunday and are counted whole. A week belongs to the month that holds its "
                    "Thursday. Days after today are left empty; every earlier day, Sunday included, counts even "
                    "when it is 0.",
            "months": [], "total": 0}
    if not layout:
        return base

    starts = [mon for _, shown, prior in layout for mon in shown + prior]
    lo = min(starts) - timedelta(days=7)
    hi = min(max(starts) + timedelta(days=6), today)
    daily = _day_counts(db, scope.with_range(lo, hi), metric)

    def cmp(cur: tuple[date, date], prev: tuple[date, date]) -> dict | None:
        """cur against prev; an unfinished cur is cut at today and prev at the same number of days."""
        cf, ct = cur[0], min(cur[1], today)
        if ct < cf:
            return None
        pf, pt = prev
        pt = min(pt, pf + timedelta(days=(ct - cf).days))
        return {"cur": [cf.isoformat(), ct.isoformat()], "prev": [pf.isoformat(), pt.isoformat()],
                **compare.change(_span(daily, cf, ct), _span(daily, pf, pt))}

    for m, shown, prior in layout:
        weeks = []
        for mon in shown:
            sun = mon + timedelta(days=6)
            no = month_weeks(m).index(mon) + 1
            days = []
            for i in range(7):
                day = mon + timedelta(days=i)
                before = day - timedelta(days=7)
                days.append({"date": day.isoformat(), "weekday": WEEKDAYS[i], "future": day > today,
                             "n": daily.get(day, 0) if day <= today else None,
                             "previous": daily.get(before, 0) if before <= today else 0})
            elapsed = min(7, (today - mon).days + 1)
            total = _span(daily, mon, min(sun, today))
            vs_month = cmp((mon, sun), (prior[no - 1], prior[no - 1] + timedelta(days=6))) if no <= len(prior) else None
            weeks.append({"no": no, "from": mon.isoformat(), "to": sun.isoformat(), "running": sun > today,
                          "days_counted": elapsed, "days": days, "total": total,
                          "avg_per_day": round(total / elapsed, 1),
                          "vs_previous_week": cmp((mon, sun), (mon - timedelta(days=7), mon - timedelta(days=1))),
                          "vs_same_week_last_month": vs_month,
                          "same_week_last_month_missing": vs_month is None and no > len(prior)})
        first, last = shown[0], shown[-1] + timedelta(days=6)
        p_from = prior[0] if prior else first - timedelta(days=28)
        p_to = (prior[-1] + timedelta(days=6)) if prior else first - timedelta(days=1)
        base["months"].append({"month": m.isoformat(), "from": first.isoformat(), "to": last.isoformat(),
                               "week_count": len(shown), "running": last > today,
                               "total": _span(daily, first, min(last, today)), "weeks": weeks,
                               "vs_previous_month": cmp((first, last), (p_from, p_to)) if prior else None})
    base["total"] = sum(mo["total"] for mo in base["months"])
    return base


# ------------------------------------------------------------------------------ which project / form pulled a month down
def _month_counts(db: Session, scope: Scope, metric: str) -> dict[tuple[date, int, str], int]:
    sets = metrics.status_sets(db)
    pred = metrics.predicates(scope, sets)[metric]
    month = func.date_trunc("month", METRIC_DATE[metric]).cast(Date)
    label = _form_label()
    q = (metrics._form_from().add_columns(month.label("m"), Form.project_id.label("pid"), label.label("form"),
                                          metrics.tally().label("n"))
         .where(*metrics.dim_conditions(scope), pred).group_by(month, Form.project_id, label))
    return {(r["m"], r["pid"], r["form"]): int(r["n"]) for r in db.execute(q).mappings()}


def _month_end(m: date) -> date:
    return m + relativedelta(months=1) - timedelta(days=1)


def month_drivers(db: Session, scope: Scope, metric: str = "received", today: date | None = None) -> dict:
    """For every calendar month touched by the filters: total vs the month before, and the projects / forms
    behind the change. The month in progress is compared with the same number of days of the month before."""
    if metric not in METRIC_DATE:
        raise ValueError(metric)
    today = today or date.today()
    months, d = [], scope.date_from.replace(day=1)
    while d <= scope.date_to and d <= today:
        months.append(d)
        d += relativedelta(months=1)
    base = {"metric": metric, "definition": metrics.DEFINITIONS[metric], "months": []}
    if not months:
        return base

    first_prev = months[0] - relativedelta(months=1)
    end = min(_month_end(months[-1]), today)
    counts = _month_counts(db, scope.with_range(first_prev, end), metric)

    # the month in progress: the previous month is cut at the same day number
    live = months[-1] if months[-1] <= today < _month_end(months[-1]) else None
    live_prev: dict[tuple[int, str], int] = {}
    if live is not None:
        p0 = live - relativedelta(months=1)
        p1 = min(p0 + timedelta(days=today.day - 1), _month_end(p0))
        live_prev = {(pid, f): n for (m, pid, f), n in _month_counts(db, scope.with_range(p0, p1), metric).items()}
    names = _names(db)

    def of_month(m: date) -> dict[tuple[int, str], int]:
        return {(pid, f): n for (mm, pid, f), n in counts.items() if mm == m}

    for m in months:
        cur = of_month(m)
        prev = live_prev if m == live else of_month(m - relativedelta(months=1))
        per_project: dict[int, dict] = {}
        for key in set(cur) | set(prev):
            pid, form = key
            if pid not in names:
                continue
            c, p = cur.get(key, 0), prev.get(key, 0)
            proj = per_project.setdefault(pid, {"project_id": pid, "project": names[pid][0], "client": names[pid][1],
                                                "current": 0, "previous": 0, "forms": []})
            proj["current"] += c
            proj["previous"] += p
            if c != p:
                proj["forms"].append({"form": form, "current": c, "previous": p, "delta": c - p})
        total_c, total_p = sum(cur.values()), sum(prev.values())

        def side(sign: int) -> list[dict]:
            """Projects with at least one form that moved in this direction; `delta` sums only those forms, so a
            project that grew overall can still show the form that fell (and the other way round)."""
            out = []
            for proj in per_project.values():
                moved = sorted((f for f in proj["forms"] if f["delta"] * sign > 0), key=lambda f: f["delta"] * sign * -1)
                if not moved:
                    continue
                out.append({"project_id": proj["project_id"], "project": proj["project"], "client": proj["client"],
                            "current": proj["current"], "previous": proj["previous"],
                            "net_delta": proj["current"] - proj["previous"],
                            "delta": sum(f["delta"] for f in moved), "form_count": len(moved),
                            "forms": moved[:MAX_FORMS]})
            out.sort(key=lambda p: p["delta"] * sign * -1)
            return out

        decliners, gainers = side(-1), side(1)
        gross = sum(-p["delta"] for p in decliners) or 1
        for p in decliners:
            p["share_of_decline_pct"] = round(100.0 * -p["delta"] / gross, 1)
        ch = compare.change(total_c, total_p)
        base["months"].append({
            "month": m.isoformat(), "partial": m == live, "current": total_c, "previous": total_p,
            "delta": ch["delta"], "pct_change": ch["pct_change"], "direction": ch["direction"],
            "previous_month": (m - relativedelta(months=1)).isoformat(),
            "decliners": decliners[:MAX_DECLINERS], "decliner_count": len(decliners),
            "gainers": gainers[:MAX_GAINERS], "gainer_count": len(gainers)})
    return base
