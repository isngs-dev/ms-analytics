"""Deterministic mock data: synthetic workbooks that flow through the real ETL.

Builds 5 clients x 3 projects (15), 12 people, ~3 years of activity, in the same messy sheet
shapes seen in the real Drive folder (header variants, blank headers, 2-digit years, RW and
Escalation tabs, Master, pivot and credential tabs, a multi-project file, a file without a
middle name part). Everything is fictional.

Built-in stories so the dashboards have something to show:
  - BRK Drive-Thru Teller: incoming volume declines through 2026
  - CST Burger Quality:    rework rate climbs from ~3% to ~14%
  - DLM Hotel Lobby:       editing backlog grows in 2026 (pending piles up)
  - NVA Car Wash:          project ends Dec 2025
  - EQX Service Lane:      project starts in 2025
  - two projects use 'Finalized' only (no 'Edited & Saved'), like several real workbooks

Run:  python -m app.seed.mock --reset
"""
from __future__ import annotations

import argparse
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import text

from ..config import settings
from ..etl.sources import FileMeta, InMemorySource, InMemoryWorkbook

AS_OF = date(2026, 11, 10)
DEFAULT_START = date(2024, 1, 1)

ISN_EDITORS = ["Asha Rao", "Bikram Sen", "Chitra Nair", "Dev Malik", "Esha Kapoor", "Farid Khan",
               "Gita Menon", "Hari Joshi"]
FREELANCERS = ["Ira Bose", "Jai Verma", "Kiran Das", "Lata Iyer"]
QC_MEMBERS = ["Asha Rao", "Dev Malik", "Gita Menon", "Hari Joshi"]
EDITOR_TYPE = {**{n: "iSN Team" for n in ISN_EDITORS}, **{n: "Freelancer" for n in FREELANCERS}}

CITIES = [("Austin", "TX"), ("Denver", "CO"), ("Tampa", "FL"), ("Columbus", "OH"), ("Boise", "ID"),
          ("Albany", "NY"), ("Reno", "NV"), ("Raleigh", "NC"), ("Tulsa", "OK"), ("Omaha", "NE")]
ROOT_CAUSES = ["Instruction missed during edit", "Shopper comment not reconciled with score",
               "Location mismatch not caught", "Grammar issue overlooked", "Template changed mid-wave"]
PREVENTIVE = ["Checklist added to editing SOP", "Peer review for first 5 shops", "Briefing on updated form",
              "Auto-check for location name", ""]
QC_FEEDBACK = ["Fixed grammar in Q4 comment", "Aligned comment with score", "Added missing detail on Q9",
               "Removed unsupported claim", ""]


@dataclass
class ProjectCfg:
    client: str
    name: str
    base: int  # forms per month at normal volume
    qc: bool
    start: date = date(2024, 1, 1)
    end: date | None = None
    trend: str = "flat"  # flat | decline
    rework: tuple[float, float] = (0.04, 0.04)  # rework rate at start -> end of the whole period
    backlog_2026: bool = False
    finalized_only: bool = False  # no 'Edited & Saved' (matches several real workbooks)
    group: str = "single"  # single | multi | noname
    editors: list[str] = field(default_factory=list)


PROJECTS = [
    ProjectCfg("NVA", "Fuel Station Audit", 90, qc=True, editors=ISN_EDITORS[:4] + FREELANCERS[:1]),
    ProjectCfg("NVA", "Car Wash Visits", 55, qc=False, end=date(2025, 12, 31), editors=ISN_EDITORS[2:5]),
    ProjectCfg("NVA", "Store Cleanliness", 70, qc=True, editors=ISN_EDITORS[1:5]),
    ProjectCfg("BRK", "Bank Teller Shop", 110, qc=True, editors=ISN_EDITORS[:5]),
    ProjectCfg("BRK", "Drive-Thru Teller", 80, qc=True, trend="decline", editors=ISN_EDITORS[3:7]),
    ProjectCfg("BRK", "Call Authentication", 45, qc=False, finalized_only=True, editors=FREELANCERS),
    ProjectCfg("CST", "Pizza Launch Wave", 100, qc=False, editors=FREELANCERS + ISN_EDITORS[5:7]),
    ProjectCfg("CST", "Burger Quality", 85, qc=True, rework=(0.03, 0.14), editors=ISN_EDITORS[4:8]),
    ProjectCfg("CST", "Coffee Service", 60, qc=False, editors=ISN_EDITORS[5:8] + FREELANCERS[:2]),
    ProjectCfg("DLM", "Airport Retail", 75, qc=True, editors=ISN_EDITORS[:3] + FREELANCERS[2:]),
    ProjectCfg("DLM", "Mall Concierge", 40, qc=False, group="multi", editors=ISN_EDITORS[2:5]),
    ProjectCfg("DLM", "Hotel Lobby", 65, qc=True, group="multi", backlog_2026=True,
               editors=ISN_EDITORS[4:8]),
    ProjectCfg("EQX", "Auto Dealer Visit", 95, qc=True, editors=ISN_EDITORS[:4] + FREELANCERS[:1]),
    ProjectCfg("EQX", "Service Lane", 60, qc=False, start=date(2025, 3, 1), editors=ISN_EDITORS[1:4]),
    ProjectCfg("EQX", "Parts Counter", 35, qc=False, finalized_only=True, group="noname",
               editors=FREELANCERS[:3]),
]


@dataclass
class Style:
    short_year: bool
    loc_header: str
    ops_header: str
    input_header: str
    tx_header: str
    blank_qc_header: bool
    title_row: bool
    float_ids: bool
    prefix_form: bool

    def fmt(self, d: date | None):
        if d is None:
            return ""
        return f"{d.month}/{d.day}/{d.year % 100:02d}" if self.short_year else f"{d.month}/{d.day}/{d.year}"


def _style(rng: random.Random) -> Style:
    return Style(short_year=rng.random() < 0.3, loc_header=rng.choice(["Class / Location", "Location"]),
                 ops_header=rng.choice(["Ops Status", "OPS Status"]),
                 input_header=rng.choice(["Input Date", "Input date"]),
                 tx_header=rng.choice(["Transaction Date", "Transation Date"]),
                 blank_qc_header=rng.random() < 0.3, title_row=rng.random() < 0.25,
                 float_ids=rng.random() < 0.2, prefix_form=rng.random() < 0.5)


@dataclass
class FormRec:
    job: str
    received: date | None
    shop: date
    input_status: str
    editor: str | None
    editor_type: str
    edit_date: date | None
    ops: str | None
    qc_member: str | None
    qc_date: date | None
    qc_status: str | None
    form_name: str
    location: str
    comments: str
    feedback: str
    final: bool  # reached a finished state (edited / finalised)


def _months(start: date, end: date):
    d = date(start.year, start.month, 1)
    while d <= end:
        yield d
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def _season(m: int) -> float:
    return {1: 1.05, 2: 0.95, 3: 1.1, 4: 1.0, 5: 1.0, 6: 0.95, 7: 0.9, 8: 0.9, 9: 1.05, 10: 1.1,
            11: 1.05, 12: 0.8}[m]


def _business_days(first: date, last: date) -> list[date]:
    out, d = [], first
    while d <= last:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _pick(rng, seq):
    return seq[rng.randrange(len(seq))]


def gen_project(cfg: ProjectCfg, rng: random.Random, period_start: date) -> tuple[list[FormRec], list[dict], list[dict]]:
    """Returns (forms, rework rows, escalations) for one project across the whole period."""
    forms: list[FormRec] = []
    rework: list[dict] = []
    esc: list[dict] = []
    first = max(cfg.start, period_start)
    last = min(cfg.end or AS_OF, AS_OF)
    total_span = max((AS_OF - period_start).days, 1)
    job = rng.randrange(1_000_000, 9_000_000)
    variants = ["Visit", "Revisit", "Audit"][: rng.randint(1, 3)]
    stores = [f"{rng.randint(100, 9999)} {c} ({st} US)" for c, st in
              (_pick(rng, CITIES) for _ in range(40))]

    for m0 in _months(first, last):
        mend = date(m0.year + (m0.month == 12), m0.month % 12 + 1, 1) - timedelta(days=1)
        days = _business_days(max(m0, first), min(mend, last))
        if not days:
            continue
        n = cfg.base * _season(m0.month) * rng.uniform(0.85, 1.15)
        if cfg.trend == "decline" and m0.year >= 2026:
            n *= 0.93 ** (m0.month - 0.5)  # roughly -7% per month through 2026
        n = int(round(n * len(days) / 21))
        for _ in range(max(n, 0)):
            rec_d = _pick(rng, days)
            job += rng.randint(1, 6)
            lag = _pick(rng, [0, 0, 1, 1, 1, 2, 3])
            stuck = False
            if cfg.backlog_2026 and rec_d >= date(2026, 1, 1):
                lag += _pick(rng, [2, 3, 5, 8])
                stuck = rng.random() < 0.10
            editor = _pick(rng, cfg.editors)
            r = rng.random()
            input_status = "Completed" if r < 0.93 else ("Hold A" if r < 0.97 else "Hold B")
            edit_d = rec_d + timedelta(days=lag)
            ops = qc_m = qc_d = qc_s = None
            final = False
            if stuck or edit_d > AS_OF:
                edit_d = None
                ops = "Query" if stuck else None  # pending editing
            else:
                outcome = rng.choices(["ok", "incomplete", "hold"], [0.89, 0.07, 0.04])[0]
                if outcome == "incomplete":
                    ops = "Incomplete"
                elif outcome == "hold":
                    ops = "Hold A"
                else:
                    final = True
                    if cfg.qc:
                        ops = "Edited & Saved"
                        qd = edit_d + timedelta(days=_pick(rng, [0, 0, 1, 2, 4]))
                        # a small, realistic QC backlog: only recent forms may still await QC
                        recent = edit_d > AS_OF - timedelta(days=45)
                        if qd <= AS_OF and not (recent and rng.random() < 0.06):
                            qc_m = _pick(rng, [q for q in QC_MEMBERS if q != editor] or QC_MEMBERS)
                            qc_d, qc_s = qd, "Client Finalized"
                    elif cfg.finalized_only:
                        ops = _pick(rng, ["Finalized", "Finalized", "Client Finalized"])
                    else:
                        ops = "Edited & Saved"
            variant = _pick(rng, variants)
            forms.append(FormRec(
                job=str(job), received=rec_d, shop=rec_d - timedelta(days=rng.randint(1, 3)),
                input_status=input_status, editor=editor, editor_type=EDITOR_TYPE[editor],
                edit_date=edit_d, ops=ops, qc_member=qc_m, qc_date=qc_d, qc_status=qc_s,
                form_name=f"{cfg.name}: {variant}" if cfg.group != "single" else variant,
                location=_pick(rng, stores),
                comments=(f"{edit_d.month}/{edit_d.day} - {ops} - iSN" if edit_d and ops else ""),
                feedback=_pick(rng, QC_FEEDBACK) if qc_m else "", final=final))

            if final and edit_d:
                progress = (edit_d - period_start).days / total_span
                rate = cfg.rework[0] + (cfg.rework[1] - cfg.rework[0]) * progress
                if rng.random() < rate:
                    d, rounds = edit_d, rng.choices([1, 2, 3], [0.7, 0.22, 0.08])[0]
                    for k in range(rounds):
                        d = d + timedelta(days=rng.randint(1, 4))
                        if d > AS_OF:
                            break
                        last_round = k == rounds - 1
                        rework.append(dict(job=str(job), received=d, shop=forms[-1].shop,
                                           editor=_pick(rng, cfg.editors), rw_date=d,
                                           status="Finalized" if last_round else _pick(
                                               rng, ["Incomplete", "Hold A", "Query"]),
                                           form_name=forms[-1].form_name, location=forms[-1].location,
                                           qc_member=qc_m, parent_received=rec_d,
                                           category=_pick(rng, ["Grammar", "Missed Instruction",
                                                                "Contradication", ""])))
                if rng.random() < 0.004 * (3 if (m0.year, m0.month) == (2025, 9) else 1):
                    ed = edit_d + timedelta(days=rng.randint(5, 20))
                    if ed <= AS_OF:
                        esc.append(dict(job=str(job), received=ed, editor=editor,
                                        qc_member=_pick(rng, QC_MEMBERS), qc_date=ed,
                                        root=_pick(rng, ROOT_CAUSES), prev=_pick(rng, PREVENTIVE),
                                        parent_received=rec_d))
    return forms, rework, esc


# ----------------------------------------------------------------------------- rendering
def _month_header(st: Style) -> list[str]:
    return [st.input_header, "Form", st.loc_header, "Shop ID", "Shop Date", "Input Status", "Editor",
            "Editor Name", st.tx_header, st.ops_header, "Comments to shopper", "Hold/Incomplete Category",
            "QC Member", "QC Date", "" if st.blank_qc_header else "QC Status", "Feedback", "Client Name",
            "Client Escalation", "Company's Name", "Error Category", "Platform", ""]


def _render_form(f: FormRec, st: Style, client: str, rng: random.Random, project: str) -> list:
    job: object = float(f.job) if st.float_ids else f.job + (" " if rng.random() < 0.01 else "")
    editor = f.editor
    received: object = st.fmt(f.received)
    if f.final and rng.random() < 0.005:
        editor = None  # edited with no editor name -> Data Health
    if rng.random() < 0.002:
        received = ""  # missing Input Date
    elif rng.random() < 0.001:
        received = "TBD"
    return [received, f.form_name, f.location, job, st.fmt(f.shop), f.input_status,
            f.editor_type if editor else "", editor or "", st.fmt(f.edit_date), f.ops or "", f.comments, "",
            f.qc_member or "", st.fmt(f.qc_date), f.qc_status or "", f.feedback, client, "", "", "QCD",
            "Sassie", 1]


def _template_row(client: str) -> list:
    return [""] * 16 + [client, "", "", "QCD", "Sassie", ""]


def _quarter_of(d: date) -> tuple[int, int]:
    return d.year, (d.month - 1) // 3 + 1


def build_mock_source(seed: int = 42, start: date = DEFAULT_START) -> InMemorySource:
    rng = random.Random(seed)
    per_project = {}
    for cfg in PROJECTS:
        prng = random.Random(f"{seed}:{cfg.client}:{cfg.name}")
        per_project[cfg.name] = (cfg, _style(prng), gen_project(cfg, prng, start))

    # group projects into workbooks per quarter
    buckets: dict[tuple, list] = {}
    for cfg, st, (forms, rw, esc) in per_project.values():
        for y, q in sorted({_quarter_of(f.received) for f in forms if f.received}):
            key = (cfg.client, cfg.group if cfg.group != "single" else cfg.name, y, q)
            buckets.setdefault(key, []).append((cfg, st, forms, rw, esc))

    source = InMemorySource()
    for (client, gname, y, q), members in sorted(buckets.items()):
        cfg0, st = members[0][0], members[0][1]
        mid = {"multi": "Multi-Projects", "noname": ""}.get(cfg0.group, cfg0.name)
        name = f"{client}_{mid}_Q{q} {y}" if mid else f"{client}_Q{q} {y}"
        months = [date(y, 3 * (q - 1) + i, 1) for i in (1, 2, 3)]
        tabs: dict[str, list[list]] = {}
        rw_rows, esc_rows = [], []
        for m in months:
            rows: list[list] = []
            if st.title_row:
                rows.append([f"{client} tracker {y}"])
            rows.append(_month_header(st))
            body = []
            for cfg, _, forms, rw, esc in members:
                body += [f for f in forms if f.received and (f.received.year, f.received.month) == (m.year, m.month)]
            body.sort(key=lambda f: (f.received, f.job))
            rrng = random.Random(f"{seed}:{name}:{m}")
            for f in body:
                rows.append(_render_form(f, st, client, rrng, cfg0.name))
                if rrng.random() < 0.004:  # accidental duplicate row
                    rows.append(_render_form(f, st, client, rrng, cfg0.name))
            rows.extend(_template_row(client) for _ in range(rrng.randint(0, 6)))
            tabs[m.strftime("%B")] = rows
        for cfg, _, forms, rw, esc in members:
            in_q = lambda d: d and _quarter_of(d) == (y, q)
            rw_rows += [r for r in rw if in_q(r["parent_received"])]
            esc_rows += [e for e in esc if in_q(e["parent_received"])]
        rw_rows.sort(key=lambda r: (r["rw_date"], r["job"]))
        tabs["RW"] = [["Input Date", "Form", "Class", "Job ID", "Shop Date", "Status", "Editor", "RW Editor",
                       "Transaction Date", "Status", "Comments to shopper", "QC Member", "QC Date", "Status",
                       "Feedback", "Error Categories", "Start Time", "End Time", "Submit Date and Time",
                       "Edited Date and Time"]] + [
            [st.fmt(r["received"]), r["form_name"], r["location"], r["job"], st.fmt(r["shop"]),
             "Completed", EDITOR_TYPE[r["editor"]], r["editor"], st.fmt(r["rw_date"]), r["status"],
             f"{r['rw_date'].month}/{r['rw_date'].day} - {r['status']} - iSN", r["qc_member"] or "", "", "",
             "", r["category"], "", "", "", ""] for r in rw_rows]
        tabs["Escalation"] = [["Input Date", "Shop ID", "Editor", "Editor name", "QC Member", "QC Date",
                               "Feedback / Client Escalation", "Root Cause", "Preventive Action",
                               "Remarks"]] + [
            [st.fmt(e["received"]), e["job"], EDITOR_TYPE[e["editor"]], e["editor"], e["qc_member"],
             st.fmt(e["qc_date"]), "Client flagged an error in the report", e["root"], e["prev"], ""]
            for e in sorted(esc_rows, key=lambda e: e["received"])]
        tabs["Master"] = [["Editor", "Status", "Error Categories", "Hold Reasons", "Editor Name",
                           "Error Categories"],
                          ["Freelancer", "Edited & Saved", "Grammar", "Insufficient information", "", "Grammar"],
                          ["iSN Team", "Finalized", "Missed Instruction", "Closed Location", "",
                           "Missed Instruction"],
                          ["", "Client Finalized", "Contradication", "", "", "Contradication"],
                          ["", "", "", "", "", "All"]]
        tabs[f"PT {months[0].strftime('%B')}"] = [["Editor Name", "COUNTA of Ops Status"], ["(pivot)", 0]]
        tabs["Login Details"] = [["Platform Link", "https://example.invalid/login"],
                                 ["ID", "mock-user"], ["Password", "mock-not-a-real-password"]]
        qend = date(y + (q == 4), (3 * q) % 12 + 1, 1) - timedelta(days=1)
        modified = datetime.combine(min(qend + timedelta(days=3), AS_OF), datetime.min.time(),
                                    tzinfo=timezone.utc) + timedelta(hours=9)
        meta = FileMeta(f"mock-{client}-{gname}-{y}-Q{q}".replace(" ", "_"), name, y, q, modified)
        source.workbooks.append(InMemoryWorkbook(meta, tabs))
    return source


# ----------------------------------------------------------------------------- CLI
_RESET_TABLES = ["escalations", "rework", "forms", "sync_issue", "sync_log", "src_sheet", "src_file",
                 "snapshot_monthly", "dim_project", "client_alias", "dim_client", "person_alias",
                 "dim_person", "dim_error_category"]


def reset_data(session) -> None:
    """Wipes loaded data (not mapping tables). Refuses unless DATA_SOURCE=mock."""
    if settings.data_source != "mock":
        raise SystemExit("Refusing to reset: DATA_SOURCE is not 'mock'.")
    session.execute(text("TRUNCATE " + ", ".join(_RESET_TABLES) + " RESTART IDENTITY CASCADE"))
    session.commit()


def main():
    from ..db import SessionLocal
    from ..etl.sync import run_sync
    from .mapping import seed_mappings

    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="wipe loaded data first (mock mode only)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    args = ap.parse_args()

    with SessionLocal() as s:
        if args.reset:
            reset_data(s)
        seed_mappings(s)
        s.commit()
        src = build_mock_source(args.seed, args.start)
        print(f"generated {len(src.workbooks)} workbooks; loading through the ETL ...")
        log = run_sync(s, src, trigger="seed", force=True)
        print(f"sync #{log.id}: {log.status}, files={log.files_changed}, "
              f"rows={log.rows_upserted}, rejected={log.rows_rejected}")


if __name__ == "__main__":
    main()
