"""End-to-end ETL tests on synthetic workbooks that mimic the real header shapes."""
import json
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.etl.sources import FileMeta, InMemorySource, InMemoryWorkbook
from app.etl.sync import run_sync
from app.models import (DimClient, DimErrorCategory, DimProject, Escalation, Form, Rework, SrcSheet, SyncIssue,
                        SyncLog)

HEADER = ["Input Date", "Form", "Class / Location", "Shop ID", "Shop Date", "Input Status", "Editor",
          "Editor Name", "Transaction Date", "Ops Status", "Comments to shopper",
          "Hold/Incomplete Category", "QC Member", "QC Date", "QC Status", "Feedback", "Client Name",
          "Client Escalation", "Company's Name", "Error Category", "Platform", ""]


def row(received, form, job, edit_date, status, editor="Ed One", qc_member="", qc_date="", qc_status="",
        client="TST"):
    return [received, form, "Loc 1 (TX US)", job, "12/30/25", "Completed", "iSN Team", editor, edit_date,
            status, "", "", qc_member, qc_date, qc_status, "", client, "", "", "QCD", "Sassie", 1]


TEMPLATE_ROW = [""] * 16 + ["TST", "", "", "QCD", "Sassie", ""]
RW_HEADER = ["Input Date", "Form", "Class", "Job ID", "Shop Date", "Status", "Editor", "RW Editor",
             "Transaction Date", "Status", "Comments to shopper", "QC Member", "QC Date", "Status",
             "Feedback", "Error Categories"]
ESC_HEADER = ["Input Date", "Shop ID", "Editor", "Editor name", "QC Member", "QC Date",
              "Feedback / Client Escalation", "Root Cause", "Preventive Action", "Remarks"]


def t(h=10):
    return datetime(2026, 5, 1, h, tzinfo=timezone.utc)


def alpha(modified=None, jan_extra=None):
    jan = [["Alpha tracker"], HEADER,
           row("1/2/2026", "Alpha Form", "1001", "1/2/2026", "Edited & Saved", qc_member="Quin Q",
               qc_date="1/3/2026", qc_status="Client Finalized"),
           row("1/2/2026", "Alpha Form", 1002.0, "1/2/2026", "Finalized"),
           row("1/3/2026", "Alpha Form", "1003 ", "1/3/2026", "Hold A"),
           TEMPLATE_ROW,
           row("1/4/2026", "Alpha Form", "1001", "1/4/2026", "Finalized")]  # duplicate of 1001
    jan += jan_extra or []
    feb = [["", "Form", "Location", "Shop ID", "Shop Date", "Input Status", "Editor", "Editor Name",
            "Transation Date", "OPS Status", "QC Member", "QC Date", ""],
           ["2/2/26", "Alpha Form", "L", "2001", "01/30/26", "Completed", "Freelancer", "Fran F",
            "2/2/26", "Edited & Saved", "", "", ""],
           ["2/3/26", "Alpha Form", "L", "2002", "01/30/26", "Completed", "Freelancer", "Fran F",
            "2/3/26", "Weird New Status", "", "", ""]]
    rw = [RW_HEADER,
          ["1/10/2026", "Alpha Form", "L", "1002", "12/30/25", "Completed", "iSN Team", "Ed One",
           "1/10/2026", "Incomplete", "", "", "", "", "", ""],
          ["1/12/2026", "Alpha Form", "L", "1002", "12/30/25", "Completed", "iSN Team", "Ed One",
           "1/12/2026", "Hold A", "", "", "", "", "", ""],
          ["1/14/2026", "Alpha Form", "L", "1002", "12/30/25", "Completed", "iSN Team", "Ed One",
           "1/14/2026", "Finalized", "", "", "", "", "", "Grammar"]]
    esc = [ESC_HEADER,
           ["2/1/2026", "1002", "iSN Team", "Ed One", "Quin Q", "2/2/2026", "Client unhappy",
            "Missed instruction", "Checklist", ""]]
    master = [["Editor", "Status", "Error Categories"], ["Freelancer", "Finalized", "Grammar"],
              ["iSN Team", "Query", "Missed Instruction"], ["", "", "All"]]
    login = [["Platform Link", "https://example.invalid"], ["ID", "x"], ["Password", "SECRET-DO-NOT-READ"]]
    return InMemoryWorkbook(
        FileMeta("file-alpha", "TST_Alpha Shop_Q1 2026", 2026, 1, modified or t()),
        {"January": jan, "February": feb, "RW": rw, "Escalation": esc, "Master": master,
         "PT January": [["x"]], "Login Details": login})


def multi():
    h = HEADER
    rows = [h,
            row("1/5/2026", "Bank One: Call", "7001", "1/5/2026", "Finalized", client="HSB"),
            row("1/5/2026", "Bank Two: Visit", "7002", "1/5/2026", "Finalized", client="HSB")]
    return InMemoryWorkbook(FileMeta("file-multi", "HSB_Multi-Projects_Q1 2026", 2026, 1, t()),
                            {"January": rows})


def noproj():
    rows = [HEADER, row("1/6/2026", "Orlando Audit", "9001", "1/6/2026", "Finalized", client="CXE")]
    return InMemoryWorkbook(FileMeta("file-cxe", "CXE_Q1 2026", 2026, 1, t()), {"January": rows})


def count(session, model, **flt):
    q = select(func.count()).select_from(model)
    for k, v in flt.items():
        q = q.where(getattr(model, k) == v)
    return session.scalar(q)


def test_full_sync(session):
    src = InMemorySource([alpha(), multi(), noproj()])
    log = run_sync(session, src, trigger="manual")
    assert log.status == "ok" and log.files_scanned == 3 and log.files_changed == 3

    # credential tabs are never fetched, whatever the rules say; every other tab is read (a pivot is kept as raw rows)
    fetched = {tab for _, tab in src.reads}
    assert "Login Details" not in fetched and "PT January" in fetched

    # projects: middle part of filename / Form column fallbacks
    names = set(session.scalars(select(DimProject.name)))
    assert {"Alpha Shop", "Bank One", "Bank Two", "Orlando Audit"} <= names

    alpha_forms = session.scalars(select(Form).join(DimProject).where(DimProject.name == "Alpha Shop")).all()
    ids = {f.job_id for f in alpha_forms}
    assert ids == {"1001", "1002", "1003", "2001", "2002"}  # template row skipped, ids normalised
    f1001 = next(f for f in alpha_forms if f.job_id == "1001")
    assert f1001.dup_count == 1  # duplicate counted, not inserted twice
    assert f1001.edit_status == "Finalized"  # later row in same file wins

    # event dates parsed; edited flag comes from status_map
    f2001 = next(f for f in alpha_forms if f.job_id == "2001")
    assert f2001.edit_date.isoformat() == "2026-02-02" and f2001.editor_type == "Freelancer"

    # QC detected only where QC data exists
    proj = session.scalar(select(DimProject).where(DimProject.name == "Alpha Shop"))
    assert proj.qc_detected is True
    other = session.scalar(select(DimProject).where(DimProject.name == "Bank One"))
    assert other.qc_detected is False

    # rework rounds, linked to the form
    rw = session.scalars(select(Rework).where(Rework.job_id == "1002").order_by(Rework.rw_seq)).all()
    assert [r.rw_seq for r in rw] == [1, 2, 3]
    assert [r.rw_status for r in rw] == ["Incomplete", "Hold A", "Finalized"]
    assert all(r.form_id for r in rw)

    # escalation linked to its project via job id; master seeded categories
    esc = session.scalars(select(Escalation)).one()
    assert esc.project_id == proj.id and esc.form_id is not None
    cats = set(session.scalars(select(DimErrorCategory.name)))
    assert {"Grammar", "Missed Instruction"} <= cats and "All" not in cats

    # health issues
    types = set(session.scalars(select(SyncIssue.type)))
    assert {"duplicate", "unmapped_status"} <= types


def test_incremental_and_soft_delete(session):
    src = InMemorySource([alpha()])
    run_sync(session, src)
    reads_after_first = len(src.reads)

    again = run_sync(session, src)
    assert again.files_changed == 0 and len(src.reads) == reads_after_first  # nothing re-read

    # file modified, 1003 removed from January -> soft deleted; others stay
    wb = alpha(modified=t(12))
    wb.tabs["January"] = [r for r in wb.tabs["January"] if not (len(r) > 3 and r[3] == "1003 ")]
    src2 = InMemorySource([wb])
    log = run_sync(session, src2)
    assert log.files_changed == 1
    f = session.scalar(select(Form).where(Form.job_id == "1003"))
    assert f.deleted_at is not None
    live = session.scalar(select(func.count()).select_from(Form).where(Form.deleted_at.is_(None)))
    assert live == 4


def test_broken_workbook_does_not_stop_sync(session):
    bad = InMemoryWorkbook(FileMeta("file-bad", "_Q1 2026", 2026, 1, t()), {"January": [HEADER]})
    log = run_sync(session, InMemorySource([bad, noproj()]))
    assert log.status == "partial"
    assert count(session, Form) == 1
    assert "sheet_error" in set(session.scalars(select(SyncIssue.type)))


def test_junk_rows_never_break_a_file(session):
    """Real sheets have shifted columns: a sentence as Job ID, a paragraph as a status."""
    sentence = "9/4 Hold Survey QC3 The shop was returned to the IC for the following reasons: 1. picture not visible"
    long_status = "An identical image to a response in this shop was uploaded (matching shop: /site/ReviewEval/1) on 05/02/2024"
    rows = [HEADER,
            row("1/2/2026", "F", "5001", "1/2/2026", "Finalized"),
            row("1/2/2026", "F", sentence, "1/2/2026", "Finalized"),  # junk Job ID -> rejected
            row("1/3/2026", "F", "5002", "1/3/2026", long_status)]  # long status -> kept, truncated
    rows[3][19] = "E" * 400  # over-long error category column
    rw = [RW_HEADER, ["1/10/2026", "F", "L", sentence, "12/30/25", "Completed", "iSN Team", "Ed", "1/10/2026",
                      "Hold", "", "", "", "", "", ""]]
    wb = InMemoryWorkbook(FileMeta("junk", "JNK_Proj_Q1 2026", 2026, 1, t()), {"January": rows, "RW": rw})
    log = run_sync(session, InMemorySource([wb]))
    assert log.status == "ok" and log.rows_rejected == 2  # one junk operational row + one junk rework row
    forms = {f.job_id: f for f in session.scalars(select(Form))}
    assert set(forms) == {"5001", "5002"}
    assert len(forms["5002"].edit_status) <= 64 and len(forms["5002"].error_category_raw) <= 128
    types = set(session.scalars(select(SyncIssue.type)))
    assert "bad_job_id" in types and "unmapped_status" in types


def test_absurd_years_are_rejected_not_filed_in_the_wrong_year(session):
    rows = [HEADER, row("1/2/2028", "F", "9001", "1/2/2026", "Finalized"),   # 2028: typo for 2026? never guess
            row("1/2/0204", "F", "9002", "1/2/2026", "Finalized"),
            row("1/2/2026", "F", "9003", "1/2/2026", "Finalized")]
    rows[1][4] = "1/1/2019"  # a normal old shop date is fine
    wb = InMemoryWorkbook(FileMeta("yr", "YRS_Proj_Q1 2026", 2026, 1, t()), {"January": rows})
    run_sync(session, InMemorySource([wb]))
    f = {x.job_id: x for x in session.scalars(select(Form))}
    assert f["9001"].received_date is None and f["9002"].received_date is None
    assert f["9003"].received_date.isoformat() == "2026-01-02" and f["9001"].shop_date.isoformat() == "2019-01-01"
    assert sum(1 for i in session.scalars(select(SyncIssue)) if i.type == "bad_date" and "outside" in (i.detail or "")) == 2


def test_date_column_and_email_tab_aliases(session):
    hdr = ["Date", "Form", "Shop Name", "Shop ID", "Shop Date", "Input Status", "Editor", "Editor's Name",
           "Transaction Date", "Ops Status"]
    body = [["3/2/2026", "F", "Store 7", str(7001 + i), "3/1/2026", "Completed", "iSN Team", "Ed One", "3/2/2026",
             "Finalized"] for i in range(3)]
    rows = [hdr, *body]
    wb = InMemoryWorkbook(FileMeta("al", "ALI_Proj_Q1 2026", 2026, 1, t()),
                          {"March": rows, "E mail to the shopper": [["Dear shopper"]], "Copy of March": rows})
    src = InMemorySource([wb])
    run_sync(session, src)
    f = session.scalar(select(Form).where(Form.job_id == "7001"))
    assert f.received_date.isoformat() == "2026-03-02" and f.location == "Store 7" and f.editor_id
    # the e-mail template and the 'Copy of' tab are read too, but add no second form for the same Job ID
    assert {tab for _, tab in src.reads} == {"March", "E mail to the shopper", "Copy of March"}
    assert session.scalar(select(func.count()).select_from(Form).where(Form.job_id == "7001")) == 1
    sheets = {s.tab_name: s for s in session.scalars(select(SrcSheet))}
    assert sheets["Copy of March"].kind == "supplementary" and sheets["Copy of March"].rows_duplicate == 3
    assert sheets["Copy of March"].rows_loaded == 0 and sheets["E mail to the shopper"].kind == "reference"
    assert f.source_sheet_id == sheets["March"].id  # the real tab keeps ownership of the row


FEEDBACK_HEADER = ["Sr. No.", "Date", "Project Name", "Report Name", "Job Id", "Editor Type", "Editor Name",
                   "Feedback Session Mode", "Feedback Details", "QC Member", "Error Type", "RCA", "Corrective Action"]


def kept_workbook():
    april = [HEADER] + [row("4/2/2026", "Kept Form", str(3001 + i), "4/2/2026", "Finalized") for i in range(3)]
    # a form-like tab the rules do not count: one Job ID already exists (with a stale status), two are new
    incomplete = [HEADER,
                  row("4/2/2026", "Kept Form", "3001", "4/2/2026", "Incomplete"),
                  row("4/3/2026", "Kept Form", "3998", "4/3/2026", "Incomplete"),
                  row("4/3/2026", "Kept Form", "3999", "4/3/2026", "Hold A")]
    feedback = [FEEDBACK_HEADER,
                [1, "4/10/2026", "Kept", "Report A", "3001", "Freelancer", "Ed One", "Phone Call", "Bad grammar",
                 "Quin Q", "Grammar", "Rushed", "Noted"],
                [2, "4/11/2026", "Kept", "Report B", "3002", "iSN Team", "Ed One", "Email", "Missed item",
                 "Quin Q", "Missed Instruction", "", ""],
                [3, "4/12/2026", "Kept", "Report C", "3003", "iSN Team", "Ed One", "Email", "Wrong name", "", "", "", ""]]
    data_entry = [["Date", "Store Id", "Invoice #", "Audited Qty"],
                  ["4/2/2026", 6666.0, 116496246.0, 3], ["4/2/2026", 6667.0, 116496247.0, 4], [], ["", "", "", ""]]
    updates = [["Date", "Update"], ["4/1/2026", "Check the receipt photo first"]]
    return InMemoryWorkbook(
        FileMeta("kept", "TST_Kept Shop_Q2 2026", 2026, 2, t()),
        {"April": april, "Incomplete": incomplete, "Feedback": feedback, "Data Entry": data_entry,
         "Updates": updates, "Login Details": [["Password", "SECRET-DO-NOT-READ"]]})


def test_every_tab_is_kept_somewhere(session):
    from app.models import SrcRecord
    src = InMemorySource([kept_workbook()])
    log = run_sync(session, src)
    assert log.status == "ok"
    assert {tab for _, tab in src.reads} == {"April", "Incomplete", "Feedback", "Data Entry", "Updates"}  # never the login tab

    forms = {f.job_id: f for f in session.scalars(select(Form))}
    assert forms["3001"].edit_status == "Finalized"  # the stale 'Incomplete' copy never overwrites the real tab
    assert forms["3998"].extra["supplementary_tab"] == "Incomplete" and forms["3999"].edit_status == "Hold A"
    assert forms["3001"].extra.get("supplementary_tab") is None

    sheets = {s.tab_name: s for s in session.scalars(select(SrcSheet))}
    assert sheets["Incomplete"].kind == "supplementary"
    assert (sheets["Incomplete"].rows_loaded, sheets["Incomplete"].rows_duplicate) == (2, 1)  # 2 added, 1 already known
    assert sheets["Feedback"].kind == "escalation" and sheets["Feedback"].rows_loaded == 3
    esc = {e.job_id: e for e in session.scalars(select(Escalation))}
    assert esc["3001"].client_feedback == "Bad grammar" and esc["3001"].root_cause == "Rushed"
    assert esc["3001"].form_id == forms["3001"].id and esc["3002"].corrective_action is None

    # everything else is stored as written: header + every non-blank row, numbers without the '.0'
    de = sheets["Data Entry"]
    assert de.kind == "reference" and de.header == ["Date", "Store Id", "Invoice #", "Audited Qty"]
    recs = session.scalars(select(SrcRecord).where(SrcRecord.sheet_id == de.id).order_by(SrcRecord.row_no)).all()
    assert [r.cells for r in recs] == [["4/2/2026", "6666", "116496246", "3"], ["4/2/2026", "6667", "116496247", "4"]]
    assert [r.row_no for r in recs] == [2, 3] and de.rows_loaded == 2
    assert sheets["Updates"].header == ["Date", "Update"]
    # nothing from the credential tab, anywhere
    assert not any("SECRET" in json.dumps(r.cells) for r in session.scalars(select(SrcRecord)))
    assert sheets["Login Details"].kind == "ignored"

    # a forced re-read does not duplicate anything
    run_sync(session, src, force=True)
    assert session.scalar(select(func.count()).select_from(SrcRecord).where(SrcRecord.sheet_id == de.id)) == 2
    assert session.scalar(select(func.count()).select_from(Form).where(Form.job_id == "3998")) == 1
    assert session.scalar(select(func.count()).select_from(Escalation)) == 3


def test_a_supplementary_tab_that_disappears_removes_only_its_own_forms(session):
    src = InMemorySource([kept_workbook()])
    run_sync(session, src)
    wb = kept_workbook()
    wb.tabs["Incomplete"] = [["Note"], ["nothing here any more"]]
    wb.meta = FileMeta("kept", "TST_Kept Shop_Q2 2026", 2026, 2, t(12))
    run_sync(session, InMemorySource([wb]))
    live = {f.job_id for f in session.scalars(select(Form).where(Form.deleted_at.is_(None)))}
    assert "3998" not in live and "3999" not in live and {"3001", "3002", "3003"} <= live


def test_removed_files_leave_the_analytics_and_come_back(session):
    run_sync(session, InMemorySource([alpha(), multi(), noproj()]))
    live = lambda: session.scalar(select(func.count()).select_from(Form).where(Form.deleted_at.is_(None)))
    before = live()
    # the HSB multi-project workbook is deleted from Drive
    log = run_sync(session, InMemorySource([alpha(), noproj()]))
    assert live() == before - 2  # its two forms are gone from the analytics
    assert "file_removed" in set(session.scalars(select(SyncIssue.type)))
    # ... and restored when it reappears
    run_sync(session, InMemorySource([alpha(), multi(), noproj()]))
    assert live() == before


def test_broken_listing_cannot_wipe_the_database(session):
    books = [InMemoryWorkbook(FileMeta(f"f{i}", f"TST{i}_Proj_Q1 2026", 2026, 1, t()),
                              {"January": [HEADER, row("1/2/2026", "F", str(100 + i), "1/2/2026", "Finalized")]})
             for i in range(12)]
    run_sync(session, InMemorySource(books))
    before = session.scalar(select(func.count()).select_from(Form).where(Form.deleted_at.is_(None)))
    run_sync(session, InMemorySource(books[:3]))  # a listing that suddenly shows 3 of 12 files
    assert session.scalar(select(func.count()).select_from(Form).where(Form.deleted_at.is_(None))) == before
    assert "listing_shrunk" in set(session.scalars(select(SyncIssue.type)))


def test_sheet_rows_reconcile(session):
    rows = [HEADER, row("1/2/2026", "F", "1", "1/2/2026", "Finalized"), row("1/2/2026", "F", "1", "1/3/2026", "Finalized"),
            TEMPLATE_ROW, TEMPLATE_ROW, row("1/4/2026", "F", "2", "1/4/2026", "Finalized")]
    wb = InMemoryWorkbook(FileMeta("rec", "REC_Proj_Q1 2026", 2026, 1, t()), {"January": rows})
    run_sync(session, InMemorySource([wb]))
    s = session.scalar(select(SrcSheet).where(SrcSheet.tab_name == "January"))
    # 5 data rows below the header: 2 placeholders, 3 real rows (one repeat merged) -> all accounted for
    assert (s.rows_placeholder, s.rows_loaded, s.rows_rejected, s.rows_duplicate) == (2, 3, 0, 1)
    assert s.rows_placeholder + s.rows_loaded + s.rows_rejected == len(rows) - s.header_row


def test_unchanged_scheduled_check_leaves_no_history_row(session):
    src = InMemorySource([alpha()])
    run_sync(session, src, trigger="manual")
    n = session.scalar(select(func.count()).select_from(SyncLog))
    run_sync(session, src, trigger="schedule")  # nothing changed
    assert session.scalar(select(func.count()).select_from(SyncLog)) == n
    from app.models import AppSetting
    assert session.get(AppSetting, "sync_heartbeat").value["files_changed"] == 0


def test_client_name_case_is_one_client(session):
    a = InMemoryWorkbook(FileMeta("a", "IntelliShop_Gopuff_Q1 2026", 2026, 1, t()),
                         {"January": [HEADER, row("1/2/2026", "F", "1", "1/2/2026", "Finalized")]})
    b = InMemoryWorkbook(FileMeta("b", "Intellishop_Uber_Q1 2026", 2026, 1, t()),
                         {"January": [HEADER, row("1/2/2026", "F", "2", "1/2/2026", "Finalized")]})
    run_sync(session, InMemorySource([a, b]))
    assert count(session, DimClient) == 1
