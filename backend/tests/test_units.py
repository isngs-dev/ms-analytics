from datetime import date

from app.etl.discover import classify_tab, month_from_tab, parse_quarter_folder, parse_workbook_name, TabRule
from app.etl.normalize import norm_header, norm_job_id, parse_date
from app.etl.parse_sheet import map_columns, parse_sheet
from app.seed.mapping import OPERATIONAL_ALIASES, REWORK_ALIASES, SHEET_RULES


def test_parse_workbook_name_shapes():
    p = parse_workbook_name("APC_TD Bank Platform_Q1 2026")
    assert (p.prefix, p.middle, p.multi, p.quarter, p.year) == ("APC", "TD Bank Platform", False, 1, 2026)
    p = parse_workbook_name("RBG_Pizza Hut: 2026 Rise HT_Q1 2026")
    assert p.middle == "Pizza Hut: 2026 Rise HT"
    p = parse_workbook_name("CXE_Q1 2026")
    assert (p.prefix, p.middle, p.multi) == ("CXE", None, False)
    p = parse_workbook_name("CX Orlando_Q1 2026")
    assert p.prefix == "CX Orlando" and p.middle is None
    p = parse_workbook_name("HSB_Multi-Projects_Q1 2026")
    assert (p.prefix, p.middle, p.multi) == ("HSB", None, True)


def test_quarter_folder():
    assert parse_quarter_folder("Q1_2026") == (1, 2026)
    assert parse_quarter_folder("2026") is None


def test_parse_date_variants():
    assert parse_date("1/2/2026") == date(2026, 1, 2)
    assert parse_date("01/21/26") == date(2026, 1, 21)
    assert parse_date("12/29/25 ") == date(2025, 12, 29)
    assert parse_date("4/24/2025 4/25/2025") == date(2025, 4, 24)
    assert parse_date("2026-03-05") == date(2026, 3, 5)
    assert parse_date(46023) == date(2026, 1, 1)  # Sheets serial: day 0 = 1899-12-30
    assert parse_date(45658) == date(2025, 1, 1)
    assert parse_date("") is None and parse_date(None) is None
    assert parse_date("not a date") is None
    assert parse_date("13/45/2026") is None
    assert parse_date("13-01-2025") == date(2025, 1, 13)  # dash / dot separated = day first
    assert parse_date("19.10.24") == date(2024, 10, 19)
    assert parse_date("31-02-2025") is None
    # real cell texts that used to be dropped as 'bad dates'
    assert parse_date("28/11/2024") == date(2024, 11, 28)  # a first number above 12 can only be the day
    assert parse_date("15/08/2026") == date(2026, 8, 15)
    assert parse_date("14/2/2025") == date(2025, 2, 14)
    assert parse_date("11//11/26") == date(2026, 11, 11)  # doubled separator
    assert parse_date("07-10-26 (") == date(2026, 10, 7)  # trailing note after a dash date
    assert parse_date("1/2/2026") == date(2026, 1, 2) and parse_date("12/1/2026") == date(2026, 12, 1)  # still US month-first
    assert parse_date("########") is None and parse_date("I agree") is None


def test_job_id():
    assert norm_job_id(3318671.0) == "3318671"
    assert norm_job_id("33171 ") == "33171"
    assert norm_job_id("3318671.0") == "3318671"
    assert norm_job_id("  ") is None


def test_norm_header():
    assert norm_header("Class / Location") == "classlocation"
    assert norm_header("Company's Name") == "companysname"


def _rules():
    return [TabRule(p, pat, k, i, r) for p, pat, k, i, r in SHEET_RULES]


def test_classify_tabs():
    r = _rules()
    kind = lambda t: (classify_tab(t, r).kind if classify_tab(t, r) else None)
    assert kind("January") == "operational"
    assert kind("Sept 2026") == "operational"
    assert kind("Login Details") == "ignored" and not classify_tab("Login details", r).read_cells
    # only credential tabs are never read; pivots, e-mails, copies and odd tabs are read and kept as 'reference'
    assert kind("PT January") == "reference" and kind("Pivot Table 19") == "reference"
    assert classify_tab("PT January", r).read_cells and not classify_tab("PT January", r).include
    assert kind("RW") == "rework" and kind("Escalation") == "escalation"
    assert kind("Coca Cola Reworks") == "rework" and kind("Rework July") == "rework"
    assert kind("Master") == "master"
    assert kind("s email") == "reference" and kind("Email Sample to shoppers") == "reference"
    assert kind("Copy of September 2025") == "reference" and kind("Incomplete") == "reference"
    assert kind("Query to Client") == "reference"
    assert kind("Something odd") is None  # no rule: the sync stores it as a reference tab too
    from app.etl.discover import is_credential_tab
    assert is_credential_tab("Login Details") and is_credential_tab("Shopper Passwords")
    assert not is_credential_tab("Pivot Table 1")


def test_month_from_tab():
    assert month_from_tab("January", 2026) == date(2026, 1, 1)
    assert month_from_tab("Feb-25", 2026) == date(2025, 2, 1)


def test_duplicate_status_headers_resolved_by_context():
    header = ["Input date", "Form", "Class", "Shop Id", "Shop Date", "Status", "Editor", "RW Editor",
              "Transaction Date", "Status", "Comments to shopper", "QC Member", "QC Date", "Status"]
    aliases = {k: f for f, ks in REWORK_ALIASES.items() for k in ks}  # 'RW Editor' is a rework header
    fields, _ = map_columns(header, aliases)
    assert fields[5] == "input_status" and fields[9] == "edit_status" and fields[13] == "qc_status"
    assert fields[7] == "editor_name"


def test_placeholder_rows_are_skipped_silently():
    aliases = {k: f for f, ks in OPERATIONAL_ALIASES.items() for k in ks}
    rows = [
        ["Input Date", "Form", "Class / Location", "Shop ID", "Shop Date", "Input Status", "Editor",
         "Editor Name", "Transaction Date", "Ops Status", "Count"],
        ["", "F", "Store 12 (TX US)", "", "", "", "", "", "", "", 1],  # location + helper column only
        ["", "F", "", "", "", "", "", "Ed One", "", "", ""],  # has an editor but no ID -> a real problem
        ["1/2/2026", "F", "L", "77", "1/1/2026", "Completed", "iSN Team", "Ed", "1/2/2026", "Finalized", 1],
    ]
    ps = parse_sheet(rows, aliases, "operational")
    assert [r.row_no for r in ps.rows] == [3, 4]  # the placeholder row 2 never reaches the loader


REST = ["Form", "Class / Location", "Shop ID", "Shop Date", "Input Status", "Editor", "Editor Name",
        "Transaction Date", "OPS Status", "QC Member", "QC Date"]


def _sheet(first_header, second_shop_date=False):
    header = [first_header, *REST]
    data = [["2026-08-0%d" % d, "F", "Loc", str(4000 + d), "2026-07-3%d" % (d % 2), "Hold B", "Freelancer", "Kajal",
             "2026-08-0%d" % d, "Finalized", "", ""] for d in range(1, 6)]
    return [header, *data]


def test_misspelt_and_junk_input_date_headers_are_still_the_input_date():
    aliases = {k: f for f, ks in OPERATIONAL_ALIASES.items() for k in ks}
    # real header texts found in the Drive workbooks: a typo, and cells that are not even words
    for first in ["Inpute Date", "Input Date", "VIEW", "kya", "n", "FF", "DF", "D", "F", "Report Date"]:
        ps = parse_sheet(_sheet(first), aliases, "operational")
        assert len(ps.rows) == 5, first
        assert ps.rows[0].values["received_date"] == "2026-08-01", first
        assert ps.rows[0].values["shop_date"] == "2026-07-31", first
        assert first not in ps.unmapped_headers, first
    # a genuinely recognised header is not reported as a repair
    assert parse_sheet(_sheet("Input Date"), aliases, "operational").notes == []
    assert parse_sheet(_sheet("kya"), aliases, "operational").notes != []


def test_two_shop_date_columns_first_is_the_input_date():
    aliases = {k: f for f, ks in OPERATIONAL_ALIASES.items() for k in ks}
    rows = _sheet("Shop Date")
    ps = parse_sheet(rows, aliases, "operational")
    v = ps.rows[0].values
    assert v["received_date"] == "2026-08-01" and v["shop_date"] == "2026-07-31"


def test_a_text_first_column_is_not_taken_as_a_date():
    aliases = {k: f for f, ks in OPERATIONAL_ALIASES.items() for k in ks}
    rows = _sheet("Notes")
    for r in rows[1:]:
        r[0] = "see client email"
    ps = parse_sheet(rows, aliases, "operational")
    assert all("received_date" not in r.values for r in ps.rows)  # never invent a date from prose
    assert "Notes" in ps.unmapped_headers


def test_misspelt_company_and_error_category_headers_map():
    aliases = {k: f for f, ks in OPERATIONAL_ALIASES.items() for k in ks}
    assert aliases[norm_header("Comapny Name")] == "company_name"
    assert aliases[norm_header("Error Catagory")] == "error_category_raw"
    assert aliases[norm_header("Inpute Date")] == "received_date"


def test_detect_table_tells_form_tabs_feedback_registers_and_notes_apart():
    from app.etl.parse_sheet import detect_table
    from app.seed.mapping import ESCALATION_ALIASES
    op = {k: f for f, ks in OPERATIONAL_ALIASES.items() for k in ks}
    esc = {k: f for f, ks in ESCALATION_ALIASES.items() for k in ks}
    forms = _sheet("Input Date")
    assert detect_table(forms, op, esc)[0] == "operational"
    register = [["Sr. No.", "Date", "Project Name", "Job Id", "Editor Name", "Feedback Details", "QC Member", "Error Type",
                 "RCA"]] + [[i, "2026-04-0%d" % i, "P", str(500 + i), "Ed", "bad", "Q", "Grammar", "x"] for i in range(1, 5)]
    assert detect_table(register, op, esc)[0] == "escalation"
    # e-mail templates, instructions and data tables have no Job IDs in most rows: raw rows, never form tables
    assert detect_table([["Dear Shopper,"], ["Thank you for your report"]], op, esc) == (None, None)
    assert detect_table([["Date", "Update"], ["2026-04-01", "check the photo"]] * 5, op, esc) == (None, None)
    # a form-like header with fewer than 3 Job IDs is a note, not a table
    assert detect_table(_sheet("Input Date")[:3], op, esc) == (None, None)


def test_blank_headers_and_title_row():
    aliases = {k: f for f, ks in OPERATIONAL_ALIASES.items() for k in ks}
    rows = [
        ["Alpha tracker 2026"],
        ["", "Form", "Location", "Shop ID", "Shop Date", "Input Status", "Editor", "Editor Name",
         "Transation Date", "OPS Status", "QC Member", "QC Date", ""],
        ["1/2/2026", "F", "Loc", "55", "12/30/25", "Completed", "iSN Team", "A B", "1/2/2026",
         "Finalized", "C D", "1/3/2026", "Client Finalized"],
        [None, None, None, None, None, None, None, None, None, None, None, None, None, "x"],
    ]
    ps = parse_sheet(rows, aliases, "operational")
    assert ps.header_row == 2
    assert len(ps.rows) == 1
    v = ps.rows[0].values
    assert v["received_date"] == "1/2/2026" and v["edit_date"] == "1/2/2026"
    assert v["qc_status"] == "Client Finalized"


def test_database_url_from_a_hosting_platform_gets_the_psycopg_driver():
    from app.config import Settings
    assert Settings(database_url="postgres://u:p@h:5432/d").database_url == "postgresql+psycopg://u:p@h:5432/d"
    assert Settings(database_url="postgresql://u:p@h/d").database_url == "postgresql+psycopg://u:p@h/d"
    assert Settings(database_url="postgresql+psycopg://u:p@h/d").database_url == "postgresql+psycopg://u:p@h/d"


def test_production_without_a_database_url_fails_with_a_clear_message():
    import pytest
    from app.config import _DEFAULT_DB, Settings
    s = Settings(environment="production", jwt_secret="x" * 40, database_url=_DEFAULT_DB)
    with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
        s.assert_safe()
    Settings(environment="production", jwt_secret="x" * 40, database_url="postgres://u:p@h/d").assert_safe()
