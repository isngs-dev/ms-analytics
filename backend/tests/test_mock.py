from datetime import date

from sqlalchemy import func, select

from app.etl.sync import run_sync
from app.models import DimClient, DimPerson, DimProject, Escalation, Form, Rework, SyncIssue
from app.seed.mock import PROJECTS, build_mock_source

START = date(2026, 7, 1)  # short window keeps the test fast


def test_generator_is_deterministic():
    a, b = build_mock_source(7, START), build_mock_source(7, START)
    assert [w.meta.name for w in a.workbooks] == [w.meta.name for w in b.workbooks]
    assert all(x.tabs == y.tabs for x, y in zip(a.workbooks, b.workbooks))
    c = build_mock_source(8, START)
    assert any(x.tabs != y.tabs for x, y in zip(a.workbooks, c.workbooks))


def test_file_shapes_match_real_world_quirks():
    names = {w.meta.name for w in build_mock_source(7, START).workbooks}
    assert any("_Multi-Projects_" in n for n in names)  # multi-project file
    assert any(n.startswith("EQX_Q") for n in names)  # file with no middle part
    assert any(n.startswith("NVA_Fuel Station Audit_Q3 2026") for n in names)


def test_mock_flows_through_etl(session):
    src = build_mock_source(7, START)
    log = run_sync(session, src, trigger="seed")
    assert log.status == "ok"
    assert "Login Details" not in {t for _, t in src.reads}

    assert session.scalar(select(func.count()).select_from(DimClient)) == 5
    # NVA Car Wash ended in 2025, so 14 of the 15 projects are active in this window
    assert session.scalar(select(func.count()).select_from(DimProject)) == 14
    assert session.scalar(select(func.count()).select_from(Form)) > 3000
    assert session.scalar(select(func.count()).select_from(Rework)) > 50
    assert session.scalar(select(func.count()).select_from(Escalation)) >= 1
    assert session.scalar(select(func.count()).select_from(DimPerson)) <= 12

    qc_expected = {p.name for p in PROJECTS if p.qc and p.name != "Car Wash Visits"}
    qc_found = set(session.scalars(select(DimProject.name).where(DimProject.qc_detected.is_(True))))
    assert qc_found == qc_expected

    # some pending editing and QC pending exist (event-based metrics need both)
    assert session.scalar(select(func.count()).select_from(Form).where(Form.edit_date.is_(None))) > 0
    qc_pending = session.scalar(select(func.count()).select_from(Form).where(
        Form.edit_status == "Edited & Saved", Form.qc_date.is_(None)))
    assert qc_pending > 0

    types = set(session.scalars(select(SyncIssue.type)))
    assert "duplicate" in types  # injected duplicate rows are detected
