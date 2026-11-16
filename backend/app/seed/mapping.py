"""Seed data for the admin-editable mapping layer (column_map, status_map, sheet_rule, settings).

Built from the real workbook headers (see docs/PHASE1_SCHEMA.md). Idempotent: existing rows are
left untouched, so Admin edits survive a re-seed.
Run:  python -m app.seed.mapping
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..etl.normalize import norm_header
from ..models import AppSetting, ColumnMap, SheetRule, StatusMap

# canonical field -> normalised header aliases (see etl.normalize.norm_header)
_COMMON = {
    "form_name": ["form"],
    "location": ["classlocation", "location", "class", "shopname"],
    "job_id": ["shopid", "jobid"],  # Shop ID == Job ID
    "shop_date": ["shopdate"],
    "editor_type": ["editor"],  # 'iSN Team' / 'Freelancer'
    "editor_name": ["editorname", "editorsname"],
    "qc_member": ["qcmember"],
    "qc_date": ["qcdate"],
}
OPERATIONAL_ALIASES: dict[str, list[str]] = {
    **_COMMON,
    # some workbooks call the Input Date column just 'Date' or misspell it ('Inpute Date'); a header that is
    # pure junk ('VIEW', 'kya', 'FF') is recognised from its values instead, see parse_sheet.infer_date_column
    "received_date": ["inputdate", "inputedate", "date"],
    "input_status": ["inputstatus"],
    "edit_date": ["transactiondate", "transationdate"],  # sic: real sheets misspell it
    "edit_status": ["opsstatus"],
    "comments_to_shopper": ["commentstoshopper"],
    "hold_category": ["holdincompletecategory"],
    "qc_status": ["qcstatus"],
    "qc_feedback": ["feedback"],
    "client_name_raw": ["clientname"],
    "client_escalation": ["clientescalation"],
    "company_name": ["companysname", "companyname", "comapnyname", "comapnysname"],  # sic: misspelt in real sheets
    "error_category_raw": ["errorcategory", "errorcategories", "errorcatagory"],
    "platform": ["platform"],
    "incomplete_status": ["incompletestatus"],
    "start_time": ["starttime"],
    "end_time": ["endtime"],
    "submit_datetime": ["submitdateandtime"],
    "edited_datetime": ["editeddateandtime"],
}
REWORK_ALIASES = {**OPERATIONAL_ALIASES, "editor_name": ["editorname", "editorsname", "rweditor", "reworkeditor"]}
ESCALATION_ALIASES: dict[str, list[str]] = {
    **_COMMON,
    "raised_date": ["inputdate", "inputedate", "date"],
    "client_feedback": ["feedbackclientescalation", "feedbackdetails"],
    "root_cause": ["rootcause", "rca"],
    "preventive_action": ["preventiveaction"],
    "corrective_action": ["correctiveaction", "correctiveactionpreventiveaction"],
    "remarks": ["remarks"],
    "error_category_raw": ["errortype", "errorcategory"],
}
ALIASES_BY_KIND = {
    "operational": OPERATIONAL_ALIASES,
    "rework": REWORK_ALIASES,
    "escalation": ESCALATION_ALIASES,
}

# (field, canonical value, aliases, counts_as_edited, counts_as_finalised, hold_or_incomplete)
_STATUSES = [
    ("Edited & Saved", ["editedsaved", "editedandsaved"], True, False, False),
    ("Finalized", ["finalized", "finalised"], False, True, False),
    ("Client Finalized", ["clientfinalized"], False, True, False),
    ("Reviewed", ["reviewed"], False, False, False),
    ("Query", ["query"], False, False, False),
    ("In Process", ["inprocess"], False, False, False),
    ("Collaboration Shop", ["collaborationshop"], False, False, False),
    ("Accepted", ["accepted"], False, False, False),
    ("Rejected", ["rejected"], False, False, False),
    ("Request Revision", ["requestrevision"], False, False, False),
    ("Not Scored", ["notscored"], False, False, False),
    ("Second Attempt", ["secondattempt"], False, False, False),
    ("Completed", ["completed"], False, False, False),
    ("Hold A", ["holda"], False, False, True),
    ("Hold B", ["holdb"], False, False, True),
    ("Incomplete", ["incomplete"], False, False, True),
    # --- statuses found in the real workbooks. They only unify spellings / typos so each value is one row in
    # the analytics; none of them is flagged edited or finalised (that is a business decision, see Admin).
    ("Edited & Saved", ["editedsavedfuelkit", "editedandsavedfuelkit"], True, False, False),
    ("Exported", ["exported"], False, False, False),
    ("Return to Shopper", ["returntoshopper"], False, False, False),
    ("Request Revision", ["requestrevison", "requestrevisionquery"], False, False, False),  # sic
    ("Approved", ["approved"], False, False, False),
    ("iSN Approvals", ["isnapprovals"], False, False, False),
    ("Checked", ["checked"], False, False, False),
    ("Done", ["done"], False, False, False),
    ("Pend to QA", ["pendtoqa"], False, False, False),
    ("Pend to CSM", ["pendtocsm"], False, False, False),
    ("Accepted but Excluded", ["acceptedbutexcluded"], False, False, False),
    ("Excluded", ["excluded"], False, False, False),
    ("Second Edit", ["secondedit"], False, False, False),
    ("Waiting on Intellishop", ["waitingonintellishop"], False, False, False),
    ("Moved to Folder", ["movedtofolder"], False, False, False),
    ("Phone order issue", ["phoneorderissue"], False, False, False),
    ("Emailed", ["emailed"], False, False, False),
    ("Uploaded", ["uploaded", "uploded"], False, False, False),  # sic
    ("Hold Survey", ["holdsurvey"], False, False, True),
    ("Validation - Pending", ["validationpending"], False, False, False),
    ("Needs Review", ["needsreview"], False, False, False),
    ("Pending Finalized", ["pendingfinalized"], False, False, False),
    ("Locked", ["locked"], False, False, False),
    ("New", ["new"], False, False, False),
    ("Collaboration Shop", ["collaboration"], False, False, False),
    # 'On Hold - X' / 'On Hold – X' (hyphen or en dash) are the same status with a reason
    *[(f"On Hold – {reason}", [norm_header(f"On Hold {reason}")], False, False, True) for reason in (
        "General", "Closed/Abandoned", "Other", "Second Edit", "Wrong Shop Shopped", "Picture/Receipt Issue",
        "Multiple Reasons", "Answer Clarification", "Wrong Item/Restricted Item Shopped", "Wrong Location Visited",
        "Hold for Scheduler", "Wrong Shift Shopped", "Comment Clarification", "Missing Receipt(s)",
        "Missing Picture(s)", "Picture/Receipt Quality", "Account Manager")],
]
STATUS_FIELDS = ["input_status", "edit_status", "qc_status", "incomplete_status"]

# (priority, regex on tab name, kind, include in fact counts, read cells at all)
#
# Every tab is read except credentials. A tab no rule counts as data (kind 'reference', include False) is still
# stored: its rows are kept as written, and if it is a form-like or feedback-register table the sync detects that
# from its header (see etl.parse_sheet.detect_table) and loads what the main tabs do not already have.
SHEET_RULES = [
    (10, r"login|credential|password", "ignored", False, False),  # holds plaintext credentials: never read
    (20, r"^master", "master", False, True),  # read only to seed categories
    (30, r"^pt\b|pivot", "reference", False, True),
    (40, r"email|^update|^notes?$", "reference", False, True),
    (41, r"^e[\s\-_.]*mail", "reference", False, True),  # 'E mail to the shopper'
    (42, r"^copy of ", "reference", False, True),  # copies of month tabs: only Job IDs missing elsewhere are added
    (50, r"^(rw|rework)\b", "rework", True, True),
    (55, r"re-?works?\b", "rework", True, True),  # 'Coca Cola Reworks', 'Rework July'
    (60, r"escalat", "escalation", True, True),
    (70, r"query to client", "reference", False, True),
    (80, r"^incomplete$", "reference", False, True),  # historical copy; only Job IDs missing elsewhere are added
    (90, r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s\-_]*(\d{2,4})?$",
     "operational", True, True),
]

DEFAULT_SETTINGS = {
    "level_labels": {"level1": "Client", "level2": "Project", "level3": "Form"},
    "refresh_schedule": {"interval_minutes": 10},
}


def seed_mappings(session: Session) -> dict[str, int]:
    added = {"column_map": 0, "status_map": 0, "sheet_rule": 0, "app_setting": 0}

    have = {(c.scope, c.scope_ref, c.sheet_kind, c.source_header_norm)
            for c in session.scalars(select(ColumnMap))}
    for kind, aliases in ALIASES_BY_KIND.items():
        for canon, headers in aliases.items():
            for h in headers:
                if ("global", "", kind, h) not in have:
                    session.add(ColumnMap(scope="global", scope_ref="", sheet_kind=kind,
                                          source_header_norm=h, canonical_field=canon))
                    added["column_map"] += 1

    have_s = {(m.field, m.source_value_norm) for m in session.scalars(select(StatusMap))}
    for field in STATUS_FIELDS:
        for canonical, norms, edited, final, hold in _STATUSES:
            for n in norms:
                if (field, n) not in have_s:
                    session.add(StatusMap(field=field, source_value_norm=n, canonical_value=canonical,
                                          counts_as_edited=edited, counts_as_finalised=final,
                                          is_hold_or_incomplete=hold))
                    added["status_map"] += 1

    have_r = {r.pattern for r in session.scalars(select(SheetRule))}
    for prio, pattern, kind, include, read in SHEET_RULES:
        if pattern not in have_r:
            session.add(SheetRule(priority=prio, pattern=pattern, kind=kind, include=include,
                                  read_cells=read))
            added["sheet_rule"] += 1

    have_k = {s.key for s in session.scalars(select(AppSetting))}
    for key, value in DEFAULT_SETTINGS.items():
        if key not in have_k:
            session.add(AppSetting(key=key, value=value))
            added["app_setting"] += 1

    session.flush()
    return added


if __name__ == "__main__":
    from ..db import SessionLocal

    with SessionLocal() as s:
        print(seed_mappings(s))
        s.commit()
