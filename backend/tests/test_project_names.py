"""Level-2 (project) naming rules: rows with no Form are filed under a clearly named project, and names that differ only
in case / spacing / punctuation are one project."""
from sqlalchemy import func, select

from app.etl.sources import FileMeta, InMemorySource, InMemoryWorkbook
from app.etl.sync import run_sync
from app.models import DimProject, Form
from tests.test_sync import HEADER, row, t


def cxe(file_id, quarter, rows):
    return InMemoryWorkbook(FileMeta(file_id, f"CXE_Q{quarter} 2026", 2026, quarter, t()), {"January": [HEADER, *rows]})


def names(session):
    return sorted(p.name for p in session.scalars(select(DimProject)))


def test_rows_without_a_form_are_filed_under_a_project_that_says_so(session):
    run_sync(session, InMemorySource([cxe("f1", 1, [
        row("1/6/2026", "Orlando Audit", "9001", "1/6/2026", "Finalized", client="CXE"),
        row("1/6/2026", "", "9002", "1/6/2026", "Finalized", client="CXE")])]))
    assert names(session) == ["CXE (form missing in sheet)", "Orlando Audit"]
    unnamed = session.scalar(select(Form).where(Form.job_id == "9002"))
    assert session.get(DimProject, unnamed.project_id).name == "CXE (form missing in sheet)"


def test_a_project_named_after_its_client_is_never_invented(session):
    run_sync(session, InMemorySource([cxe("f1", 1, [row("1/6/2026", "", "9002", "1/6/2026", "Finalized", client="CXE")])]))
    assert "CXE" not in names(session)


def test_spacing_and_punctuation_variants_are_one_project(session):
    run_sync(session, InMemorySource([
        cxe("f1", 1, [row("1/6/2026", "EWR - Retail Shop", "1", "1/6/2026", "Finalized", client="CXE")]),
        cxe("f2", 2, [row("1/7/2026", "EWR- Retail Shop", "2", "1/7/2026", "Finalized", client="CXE"),
                      row("1/7/2026", "ewr  -  retail shop", "3", "1/7/2026", "Finalized", client="CXE")])]))
    assert names(session) == ["EWR - Retail Shop"]
    assert len(session.scalars(select(Form)).all()) == 3


def test_trailing_dot_and_apostrophe_variants_merge_too(session):
    run_sync(session, InMemorySource([
        cxe("f1", 1, [row("1/6/2026", "Myron Mixon Barbecue Co", "1", "1/6/2026", "Finalized", client="CXE"),
                      row("1/6/2026", "Drai's", "3", "1/6/2026", "Finalized", client="CXE")]),
        cxe("f2", 2, [row("1/7/2026", "Myron Mixon Barbecue Co.", "2", "1/7/2026", "Finalized", client="CXE"),
                      row("1/7/2026", "Drais", "4", "1/7/2026", "Finalized", client="CXE")])]))
    assert names(session) == ["Drai's", "Myron Mixon Barbecue Co"]


def test_genuinely_different_projects_stay_separate(session):
    run_sync(session, InMemorySource([cxe("f1", 1, [
        row("1/6/2026", "IAH Concession", "1", "1/6/2026", "Finalized", client="CXE"),
        row("1/6/2026", "IAH Concessions", "2", "1/6/2026", "Finalized", client="CXE"),
        row("1/6/2026", "Houston Concession", "3", "1/6/2026", "Finalized", client="CXE"),
        row("1/6/2026", "HOU Concession", "4", "1/6/2026", "Finalized", client="CXE")])]))
    assert len(names(session)) == 4  # near-duplicates by meaning are for a person to merge, not for a guess


# ------------------------------------------------------------------------------ fixing what is already in the database
from app.etl.project_names import fix_project_names  # noqa: E402
from app.models import DimClient, Escalation, Rework, SrcFile  # noqa: E402
from datetime import date  # noqa: E402


def mkform(s, c, p, job, name="F"):
    s.add(Form(client_id=c.id, project_id=p.id, job_id=job, form_name=name, received_date=date(2026, 1, 5), row_hash=job))


def test_existing_variants_merge_into_the_project_with_the_most_forms(session):
    s = session
    c = DimClient(name="CXE")
    s.add(c); s.flush()
    big, small = DimProject(client_id=c.id, name="EWR - Retail Shop"), DimProject(client_id=c.id, name="EWR- Retail Shop")
    s.add_all([big, small]); s.flush()
    for i in range(3):
        mkform(s, c, big, f"b{i}")
    mkform(s, c, small, "s1")
    s.add(Escalation(client_id=c.id, project_id=small.id, job_id="s1", row_hash="e1"))
    s.add(SrcFile(drive_file_id="x", name="CXE_Q2 2026", project_id=small.id))
    s.commit()

    out = fix_project_names(s)
    s.commit()

    assert out["merged"] == 1
    assert [p.name for p in s.scalars(select(DimProject))] == ["EWR - Retail Shop"]
    assert {f.project_id for f in s.scalars(select(Form))} == {big.id}
    assert s.scalar(select(Escalation.project_id)) == big.id and s.scalar(select(SrcFile.project_id)) == big.id


def test_a_job_present_under_both_spellings_is_never_overwritten(session):
    s = session
    c = DimClient(name="CXE")
    s.add(c); s.flush()
    a, b = DimProject(client_id=c.id, name="Drai's"), DimProject(client_id=c.id, name="Drais")
    s.add_all([a, b]); s.flush()
    mkform(s, c, a, "same"); mkform(s, c, b, "same"); mkform(s, c, b, "only-b")
    s.commit()

    fix_project_names(s)
    s.commit()

    forms = s.scalars(select(Form)).all()
    assert len(forms) == 3                                   # nothing lost
    assert {f.job_id for f in forms if f.project_id == b.id} == {"same", "only-b"}
    assert {f.job_id for f in forms if f.project_id != b.id} == {"same"}   # the colliding duplicate stays where it was


def test_a_project_named_after_its_client_without_any_form_name_is_renamed(session):
    s = session
    c = DimClient(name="CXE")
    s.add(c); s.flush()
    ghost = DimProject(client_id=c.id, name="CXE")
    s.add(ghost); s.flush()
    mkform(s, c, ghost, "1", name=""); mkform(s, c, ghost, "2", name="  ")
    s.commit()

    out = fix_project_names(s)
    s.commit()

    assert out["renamed"] == 1
    assert s.get(DimProject, ghost.id).name == "CXE (form missing in sheet)"


def test_a_real_project_that_shares_its_clients_name_is_left_alone(session):
    s = session
    c = DimClient(name="Grove")
    s.add(c); s.flush()
    real = DimProject(client_id=c.id, name="Grove")
    s.add(real); s.flush()
    mkform(s, c, real, "1", name="Grove Hotel Audit")
    s.commit()

    assert fix_project_names(s) == {"renamed": 0, "merged": 0}
    assert s.get(DimProject, real.id).name == "Grove"


def test_fixing_twice_changes_nothing_more(session):
    s = session
    c = DimClient(name="CXE")
    s.add(c); s.flush()
    a, b = DimProject(client_id=c.id, name="Chotto Matte"), DimProject(client_id=c.id, name="ChottoMatte")
    s.add_all([a, b]); s.flush()
    mkform(s, c, a, "1"); mkform(s, c, b, "2")
    s.commit()
    fix_project_names(s); s.commit()
    assert fix_project_names(s) == {"renamed": 0, "merged": 0}


def test_a_live_form_replaces_a_retired_one_of_the_same_job_when_variants_merge(session):
    """A job seen under 'Love_s' in a kept workbook may share its id with a soft-deleted row of an older, retired
    workbook under 'Love's': the unique key forbids both, so the retired tombstone makes way for the live row."""
    from datetime import datetime, timezone

    s = session
    c = DimClient(name="IntelliShop")
    s.add(c); s.flush()
    keep, other = DimProject(client_id=c.id, name="Love's"), DimProject(client_id=c.id, name="Love_s")
    s.add_all([keep, other]); s.flush()
    for i in range(3):
        mkform(s, c, keep, f"k{i}")                                   # makes Love's the bigger project
    mkform(s, c, keep, "j1")
    s.flush()
    tomb = s.scalar(select(Form).where(Form.project_id == keep.id, Form.job_id == "j1"))
    tomb.deleted_at = datetime(2026, 11, 19, tzinfo=timezone.utc)      # retired with its 2025 workbook
    s.add(Rework(client_id=c.id, project_id=keep.id, job_id="j1", form_id=tomb.id, rw_seq=1, row_hash="r"))
    mkform(s, c, other, "j1"); mkform(s, c, other, "j2")               # live, same job id as the tombstone
    s.commit()

    out = fix_project_names(s)
    s.commit()

    assert out["merged"] == 1
    assert [p.name for p in s.scalars(select(DimProject))] == ["Love's"]
    live = s.scalars(select(Form).where(Form.deleted_at.is_(None), Form.job_id.in_(["j1", "j2"]))).all()
    assert {(f.job_id, f.project_id) for f in live} == {("j1", keep.id), ("j2", keep.id)}
    assert s.scalar(select(Rework.form_id)) is None                    # nothing points at the removed tombstone


def test_merged_project_shows_the_readable_spelling_not_the_filename_one(session):
    """Drive file names cannot hold ':' '/' or an apostrophe, so a workbook-derived name has '_' in their place."""
    s = session
    c = DimClient(name="IntelliShop")
    s.add(c); s.flush()
    ugly, nice = DimProject(client_id=c.id, name="Love_s"), DimProject(client_id=c.id, name="Love's")
    s.add_all([ugly, nice]); s.flush()
    for i in range(5):
        mkform(s, c, ugly, f"u{i}")        # the underscore spelling has far more forms
    mkform(s, c, nice, "n1")
    s.commit()

    fix_project_names(s)
    s.commit()

    [only] = s.scalars(select(DimProject)).all()
    assert only.name == "Love's"
    assert s.scalar(select(func.count()).select_from(Form).where(Form.project_id == only.id)) == 6


def test_retired_rows_colliding_on_both_sides_do_not_block_a_merge(session):
    from datetime import datetime, timezone

    s = session
    c = DimClient(name="IntelliShop")
    s.add(c); s.flush()
    keep, other = DimProject(client_id=c.id, name="Love_s"), DimProject(client_id=c.id, name="Love's")
    s.add_all([keep, other]); s.flush()
    for i in range(4):
        mkform(s, c, keep, f"k{i}")
    mkform(s, c, keep, "old")                      # retired under Love_s ...
    mkform(s, c, other, "old")                     # ... and retired under Love's too
    s.flush()
    for f in s.scalars(select(Form).where(Form.job_id == "old")):
        f.deleted_at = datetime(2026, 11, 19, tzinfo=timezone.utc)
    s.commit()

    out = fix_project_names(s)
    s.commit()

    assert out["merged"] == 1
    assert [p.name for p in s.scalars(select(DimProject))] == ["Love's"]
