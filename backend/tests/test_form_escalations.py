"""The 'Client Escalation' column of the form rows counts as escalations (services.form_escalations)."""
from datetime import date

from sqlalchemy import select

from app.models import DimClient, DimErrorCategory, DimPerson, DimProject, Escalation, Form
from app.services.form_escalations import sync_form_escalations

D = date


def build(s):
    c = DimClient(name="HSB")
    s.add(c)
    s.flush()
    p = DimProject(client_id=c.id, name="Multi")
    ann = DimPerson(name="Ann")
    cat = DimErrorCategory(name="Client Error")
    s.add_all([p, ann, cat])
    s.flush()

    def form(job, esc, received=D(2026, 11, 10), cat_raw="Client Error"):
        f = Form(client_id=c.id, project_id=p.id, job_id=job, received_date=received, edit_date=received,
                 editor_id=ann.id, client_escalation=esc, error_category_raw=cat_raw, row_hash=job, units=1)
        s.add(f)
        return f

    forms = {"dna": form("j1", "DNA Alert"), "blank": form("j2", "  "), "none": form("j3", None),
             "tabbed": form("j4", "Bad Editing"), "old": form("j5", "Late", received=D(2025, 3, 3))}
    s.add(Escalation(client_id=c.id, project_id=p.id, job_id="j4", raised_date=D(2026, 11, 11),
                     client_feedback="from the Escalations tab", row_hash="tab-j4"))
    s.commit()
    return c, p, forms, cat


def active(s):
    return {e.job_id: e for e in s.scalars(select(Escalation).where(Escalation.deleted_at.is_(None)))}


def test_forms_with_a_client_escalation_become_escalations(session):
    c, p, forms, cat = build(session)
    r = sync_form_escalations(session)
    rows = active(session)
    assert set(rows) == {"j1", "j4", "j5"}  # blank / empty cells are not escalations; j4 is covered by its tab row
    assert r["written"] == 2
    e = rows["j1"]
    assert (e.client_id, e.project_id, e.form_id, e.raised_date) == (c.id, p.id, forms["dna"].id, D(2026, 11, 10))
    assert e.client_feedback == "DNA Alert" and e.error_category_id == cat.id and e.editor_id == forms["dna"].editor_id
    assert e.action_status == "open" and e.extra == {"origin": "form_column"}
    assert rows["j4"].client_feedback == "from the Escalations tab"  # never counted twice
    assert rows["j5"].raised_date == D(2025, 3, 3)


def test_rerun_keeps_tracking_and_follows_the_sheet(session):
    c, p, forms, cat = build(session)
    sync_form_escalations(session)
    e = active(session)["j1"]
    e.action_status, e.action_owner, e.corrective_action = "closed", "Quin", "retrained"
    session.commit()

    assert sync_form_escalations(session) == {"written": 0, "removed": 0}  # nothing changed: nothing written
    forms["dna"].client_escalation = "DNA Alert (updated)"
    forms["dna"].received_date = D(2026, 11, 12)
    session.commit()
    sync_form_escalations(session)
    e = active(session)["j1"]
    assert e.client_feedback == "DNA Alert (updated)" and e.raised_date == D(2026, 11, 12)
    assert (e.action_status, e.action_owner, e.corrective_action) == ("closed", "Quin", "retrained")

    forms["dna"].client_escalation = None  # the cell was cleared in the sheet
    session.commit()
    assert sync_form_escalations(session)["removed"] == 1
    assert "j1" not in active(session)

    forms["dna"].client_escalation = "DNA Alert"  # and written again: the same row comes back
    session.commit()
    sync_form_escalations(session)
    assert active(session)["j1"].action_status == "closed"


def test_a_later_escalations_tab_row_replaces_the_derived_one(session):
    c, p, forms, cat = build(session)
    sync_form_escalations(session)
    session.add(Escalation(client_id=c.id, project_id=p.id, job_id="j1", raised_date=D(2026, 11, 10),
                           client_feedback="tab row", row_hash="tab-j1"))
    session.commit()
    assert sync_form_escalations(session)["removed"] == 1
    rows = [e for e in session.scalars(select(Escalation).where(Escalation.deleted_at.is_(None),
                                                                Escalation.job_id == "j1"))]
    assert [e.client_feedback for e in rows] == ["tab row"]
