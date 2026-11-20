"""API tests on a small hand-built dataset where every expected number is known."""
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import get_db
from app.etl.sources import InMemorySource
from app.main import app
from app.models import (AppUser, DimClient, DimPerson, DimProject, Escalation, Form, Rework)
from app.security import hash_password
from app.services import records, sync_runner
from app.services.records import FORM_METRICS
from tests.test_sync import alpha

PW = "a-long-test-password"
D = date


def mk_form(s, client, project, job, received, edit=None, status=None, qc=None, editor=None, qc_member=None,
            qc_status=None):
    s.add(Form(client_id=client.id, project_id=project.id, job_id=job, received_date=received,
               edit_date=edit, edit_status=status, qc_date=qc, editor_id=editor.id if editor else None,
               qc_member_id=qc_member.id if qc_member else None, qc_status=qc_status, row_hash=job,
               form_name="F", location="Loc", editor_type="iSN Team"))


@pytest.fixture()
def data(session):
    s = session
    c = DimClient(name="ACME")
    s.add(c)
    s.flush()
    p1 = DimProject(client_id=c.id, name="P1", qc_detected=True)
    p2 = DimProject(client_id=c.id, name="P2", qc_detected=False)
    ann, bob, qc1 = DimPerson(name="Ann"), DimPerson(name="Bob"), DimPerson(name="Quin")
    s.add_all([p1, p2, ann, bob, qc1])
    s.flush()
    ES, FIN, HOLD = "Edited & Saved", "Finalized", "Hold A"
    mk_form(s, c, p1, "f1", D(2026, 1, 5), D(2026, 1, 6), ES, D(2026, 1, 8), ann, qc1, "Client Finalized")
    mk_form(s, c, p1, "f2", D(2026, 1, 10), D(2026, 1, 12), ES, None, ann)
    mk_form(s, c, p1, "f3", D(2026, 1, 20), None, None, None, bob)
    mk_form(s, c, p1, "f4", D(2025, 12, 28), D(2026, 1, 3), FIN, None, bob)
    mk_form(s, c, p1, "f5", D(2026, 1, 25), D(2026, 2, 2), ES, D(2026, 2, 5), ann, qc1, "Client Finalized")
    mk_form(s, c, p1, "f6", D(2026, 1, 15), D(2026, 1, 16), HOLD, None, bob)
    mk_form(s, c, p2, "f7", D(2026, 1, 7), D(2026, 1, 9), ES, None, bob)
    s.add_all([Rework(client_id=c.id, project_id=p1.id, job_id="f1", rw_seq=1, rw_date=D(2026, 1, 20),
                      rw_editor_id=ann.id, row_hash="r1"),
               Rework(client_id=c.id, project_id=p1.id, job_id="f2", rw_seq=1, rw_date=D(2026, 1, 25),
                      rw_editor_id=bob.id, row_hash="r2")])
    s.add(Escalation(client_id=c.id, project_id=p1.id, job_id="f1", raised_date=D(2026, 1, 22),
                     editor_id=ann.id, root_cause="Missed Instruction ", row_hash="e1"))
    s.add_all([AppUser(email="v@x.test", name="V", role="viewer", password_hash=hash_password(PW)),
               AppUser(email="m@x.test", name="M", role="manager", password_hash=hash_password(PW)),
               AppUser(email="a@x.test", name="A", role="admin", password_hash=hash_password(PW))])
    s.commit()
    return {"client": c, "p1": p1, "p2": p2, "ann": ann, "bob": bob, "qc": qc1}


@pytest.fixture()
def api(engine, data, monkeypatch):
    def override():
        with Session(engine) as s:
            yield s
    app.dependency_overrides[get_db] = override
    monkeypatch.setattr(records, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(sync_runner, "SessionLocal", lambda: Session(engine))
    yield TestClient(app)
    app.dependency_overrides.clear()


def login(api, who="v"):
    r = api.post("/api/auth/login", json={"email": f"{who}@x.test", "password": PW})
    assert r.status_code == 200, r.text
    return api


JAN = {"year": 2026, "month": 1}


# ------------------------------------------------------------------------------ auth
def test_requires_login_and_roles(api):
    assert api.get("/api/analytics/overview", params=JAN).status_code == 401
    assert api.post("/api/auth/login", json={"email": "v@x.test", "password": "wrong"}).status_code == 401
    login(api, "v")
    assert api.get("/api/auth/me").json()["role"] == "viewer"
    assert api.get("/api/analytics/overview", params=JAN).status_code == 200
    assert api.post("/api/sync", params={"force": "true"}).status_code == 403  # a full re-read stays with managers
    assert api.get("/api/records/forms/export", params=JAN).status_code == 403
    assert api.get("/api/admin/users").status_code == 403


def test_cookie_is_httponly(api):
    r = api.post("/api/auth/login", json={"email": "v@x.test", "password": PW})
    assert "httponly" in r.headers["set-cookie"].lower()
    assert "password" not in r.text.lower()


def test_deactivated_user_loses_access(api, engine):
    login(api, "v")
    with Session(engine) as s:
        s.query(AppUser).filter_by(email="v@x.test").update({"active": False})
        s.commit()
    assert api.get("/api/auth/me").status_code == 401


# ------------------------------------------------------------------------------ event-based metrics
def test_overview_is_event_based(api):
    login(api)
    m = api.get("/api/analytics/overview", params=JAN).json()["metrics"]
    assert m["received"] == 6  # f1 f2 f3 f5 f6 f7
    assert m["edited"] == 3  # f1 f2 f7 (f5 was edited in Feb, f4 is finalised not edited)
    assert m["finalised"] == m["processed"] == 5  # every handled form, whatever its status (f4 included)
    assert m["processed"] == 5
    assert m["qc_completed"] == 1  # f1; f5's QC happened in Feb
    assert m["pending_editing"] == 2  # as of Jan 31: f3 and f5 (edited only on Feb 2)
    assert m["qc_pending"] == 1  # f2; P2 is not QC-applicable; f5 not yet edited on Jan 31
    assert m["editing_pct"] == 71.4  # processed 5 / (5 + pending 2)
    assert m["qc_pct"] == 50.0  # qc done 1 / (1 + qc pending 1)
    assert m["completion_pct"] == 66.7 and m["edited_rate_pct"] == 50.0  # 3 edited / 6 received
    assert all(0 <= m[k] <= 100 for k in ("editing_pct", "qc_pct", "completion_pct"))
    assert "rework" not in m  # rework rows exist in the fixture but are not part of any analytics


def test_percentages_follow_the_filters_and_never_exceed_100(api, data):
    login(api)
    seen = set()
    for params in (JAN, {"year": 2026, "month": 2}, {"year": 2026, "quarter": 1}, {**JAN, "project_id": data["p2"].id},
                   {**JAN, "editor_id": data["ann"].id}):
        m = api.get("/api/analytics/overview", params=params).json()["metrics"]
        for k in ("editing_pct", "qc_pct", "completion_pct"):
            assert m[k] is None or 0 <= m[k] <= 100, (params, k, m[k])
        seen.add((m["editing_pct"], m["qc_pct"]))
    assert len(seen) >= 3  # the rings actually move when the filters change


def test_history_reports_what_was_pending_then(api):
    login(api)
    feb = api.get("/api/analytics/overview", params={"year": 2026, "month": 2}).json()["metrics"]
    assert feb["received"] == 0 and feb["edited"] == 1 and feb["qc_completed"] == 1
    assert feb["pending_editing"] == 1  # f3 never edited
    assert feb["qc_pending"] == 1  # f2 still has no QC


def test_dimension_filters(api, data):
    login(api)
    m = api.get("/api/analytics/overview", params={**JAN, "project_id": data["p2"].id}).json()["metrics"]
    assert (m["received"], m["edited"], m["qc_pending"]) == (1, 1, 0)
    m = api.get("/api/analytics/overview", params={**JAN, "editor_id": data["ann"].id}).json()["metrics"]
    assert m["received"] == 3 and m["edited"] == 2
    assert api.get("/api/analytics/overview", params={"date_from": "2026-02-01", "date_to": "2026-01-01"}
                   ).status_code == 422


def test_week_period_and_bad_week(api):
    login(api)
    r = api.get("/api/analytics/overview", params={"year": 2026, "week": 2}).json()
    assert r["period"] == {"from": "2026-01-05", "to": "2026-01-11"}
    assert api.get("/api/analytics/overview", params={"year": 2025, "week": 53}).status_code == 422  # 2025 has 52 ISO weeks


def test_status_map_change_redefines_edited_everywhere(api):
    login(api, "a")
    assert api.get("/api/analytics/overview", params=JAN).json()["metrics"]["edited"] == 3
    r = api.put("/api/admin/status-map", json={
        "field": "edit_status", "source_value": "Finalized", "canonical_value": "Finalized",
        "counts_as_edited": True, "counts_as_finalised": True})
    assert r.status_code == 200
    assert api.get("/api/analytics/overview", params=JAN).json()["metrics"]["edited"] == 4


# ------------------------------------------------------------------------------ breakdown / series
def test_breakdowns_add_up(api):
    login(api)
    ov = api.get("/api/analytics/overview", params=JAN).json()["metrics"]
    for by in ("client", "project", "editor", "editor_type", "form"):
        rows = api.get("/api/analytics/breakdown", params={**JAN, "by": by}).json()["rows"]
        assert sum(r["received"] for r in rows) == ov["received"], by
        assert sum(r["edited"] for r in rows) == ov["edited"], by
        assert sum(r["pending_editing"] for r in rows) == ov["pending_editing"], by
    assert api.get("/api/analytics/breakdown", params={**JAN, "by": "nope"}).status_code == 422


def test_timeseries_sums_match_overview(api):
    login(api)
    ov = api.get("/api/analytics/overview", params=JAN).json()["metrics"]
    for g in ("day", "week", "month"):
        pts = api.get("/api/analytics/timeseries", params={**JAN, "granularity": g}).json()["points"]
        for k in ("received", "edited", "finalised", "qc_completed"):
            assert sum(p[k] for p in pts) == ov[k], (g, k)
    day = api.get("/api/analytics/timeseries", params={**JAN, "granularity": "day"}).json()["points"]
    assert len(day) == 31  # gaps are filled with zeros


# ------------------------------------------------------------------------------ drill-through
@pytest.mark.parametrize("metric", FORM_METRICS)
def test_drill_through_rows_equal_the_count(api, metric):
    login(api)
    count = api.get("/api/analytics/overview", params=JAN).json()["metrics"][metric]
    r = api.get("/api/records/forms", params={**JAN, "metric": metric}).json()
    assert r["total"] == count and len(r["rows"]) == count


def test_records_search_sort_columns(api):
    login(api)
    r = api.get("/api/records/forms", params={**JAN, "metric": "received", "columns": "job_id,editor",
                                              "sort": "job_id", "order": "asc"}).json()
    assert r["columns"] == ["job_id", "editor"]
    assert [x["job_id"] for x in r["rows"]] == ["f1", "f2", "f3", "f5", "f6", "f7"]
    s = api.get("/api/records/forms", params={**JAN, "search": "Bob", "metric": "received"}).json()
    assert {x["job_id"] for x in s["rows"]} == {"f3", "f6", "f7"} and s["total"] == 3
    assert api.get("/api/records/forms", params={**JAN, "columns": "evil"}).status_code == 422
    assert api.get("/api/records/forms", params={**JAN, "sort": "evil"}).status_code == 422
    assert api.get("/api/records/forms", params={**JAN, "metric": "evil"}).status_code == 422


def test_export_csv_and_xlsx(api):
    login(api, "m")
    r = api.get("/api/records/forms/export", params={**JAN, "metric": "edited", "format": "csv",
                                                     "columns": "job_id,edit_status"})
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    lines = r.text.strip().splitlines()
    assert lines[0] == "job_id,edit_status" and len(lines) == 1 + 3
    x = api.get("/api/records/forms/export", params={**JAN, "format": "xlsx"})
    assert x.status_code == 200 and x.content[:2] == b"PK"  # xlsx is a zip


# ------------------------------------------------------------------------------ compare / people / escalations
def test_compare_month_over_month(api):
    login(api)
    r = api.get("/api/analytics/compare", params={"mode": "month_vs_prev_month", "anchor": "2026-01-15"}).json()
    assert r["current"] == {"from": "2026-01-01", "to": "2026-01-31"}
    assert r["previous"] == {"from": "2025-12-01", "to": "2025-12-31"}
    rec = r["overall"]["received"]
    assert (rec["current"], rec["previous"], rec["delta"]) == (6, 1, 5) and rec["pct_change"] == 500.0
    assert rec["direction"] == "up"
    w = api.get("/api/analytics/compare", params={"mode": "week_vs_prev_month_week", "anchor": "2026-02-12"}).json()
    assert w["current"]["from"] == "2026-02-09" and w["previous"]["from"] == "2026-01-05"
    assert r["partial"] is False
    assert api.get("/api/analytics/compare", params={"mode": "nope"}).status_code == 422


def test_unfinished_period_is_compared_like_for_like(api):
    login(api)
    from datetime import date as _d, timedelta
    today = _d.today()
    r = api.get("/api/analytics/compare", params={"mode": "month_vs_prev_month", "anchor": today.isoformat()}).json()
    first = today.replace(day=1)
    if today.day < 28 or (today + timedelta(days=1)).day != 1:
        assert r["partial"] is True and r["current"]["to"] == today.isoformat()
        elapsed = (today - first).days
        prev_start = _d.fromisoformat(r["previous"]["from"])
        assert (_d.fromisoformat(r["previous"]["to"]) - prev_start).days == elapsed  # same elapsed days


def test_client_feedback_quality_of_edited_reports(api):
    login(api)
    q = api.get("/api/analytics/quality", params=JAN).json()
    o = q["overall"]
    # worked on in Jan (any outcome): f1, f2, f4 (Finalized), f6 (Hold), f7. Only f1, f2, f7 are "Edited & Saved".
    # only f1 was escalated by the client; f2 has rework rows, which no analytics counts
    assert (o["edited"], o["marked_edited"], o["escalated"], o["came_back"], o["clean"]) == (5, 3, 1, 1, 4)
    assert o["quality_pct"] == 80.0 and o["escalation_free_pct"] == 80.0 and "rework" not in o and "rework_free_pct" not in o
    ov = api.get("/api/analytics/overview", params=JAN).json()["metrics"]
    assert o["edited"] == ov["processed"] and o["marked_edited"] == ov["edited"]
    # quality check coverage: bounded, adds up, and every row follows the same rule as the total
    assert o["qc_done"] + o["qc_pending"] == o["qc_scope"] <= o["edited"]
    assert o["qc_checked_pct"] is None or 0 <= o["qc_checked_pct"] <= 100
    rows_c = api.get("/api/analytics/quality", params=JAN).json()["rows"]
    assert sum(r["qc_scope"] for r in rows_c) == o["qc_scope"] and sum(r["qc_done"] for r in rows_c) == o["qc_done"]
    assert q["rows"][0]["name"] == "ACME" and q["rows"][0]["edited"] == 5
    by_p = {r["name"]: r for r in api.get("/api/analytics/quality", params={**JAN, "by": "project"}).json()["rows"]}
    assert by_p["P1"]["quality_pct"] == 75.0 and by_p["P2"]["quality_pct"] == 100.0
    # filters narrow it; an empty cohort has no percentage rather than a fake 100
    none = api.get("/api/analytics/quality", params={**JAN, "client_id": 999999}).json()["overall"]
    assert none["edited"] == 0 and none["quality_pct"] is None
    assert api.get("/api/analytics/quality", params={**JAN, "by": "bogus"}).status_code == 422


def test_drilldown_columns_fit_the_metric(api):
    login(api)
    pend = api.get("/api/records/forms", params={**JAN, "metric": "pending_editing"}).json()
    # a pending form has no edit date / QC data yet, so those are not default columns for it
    assert {"job_id", "received_date", "input_status", "source_file"} <= set(pend["columns"])
    assert not {"edit_date", "qc_date", "qc_member", "qc_status"} & set(pend["columns"])
    qc = api.get("/api/records/forms", params={**JAN, "metric": "qc_completed"}).json()
    assert {"qc_date", "qc_member", "qc_status"} <= set(qc["columns"])
    # explicit columns always win; no metric keeps the general default
    assert api.get("/api/records/forms", params={**JAN, "metric": "pending_editing", "columns": "job_id"}
                   ).json()["columns"] == ["job_id"]
    assert "edit_date" in api.get("/api/records/forms", params=JAN).json()["columns"]
    # "stage" is derived, so rows whose Ops / QC status cell is blank still say where they are
    r = api.get("/api/records/forms", params={**JAN, "columns": "job_id,stage,edit_status", "page_size": 50}).json()
    stage = {x["job_id"]: x["stage"] for x in r["rows"]}
    assert stage["f1"] == "QC done" and stage["f3"] == "Waiting for editing" and stage["f2"] == "Edited & Saved"
    assert stage["f6"] == "Hold A"


def test_all_years_range_covers_the_whole_dataset(api):
    login(api)
    from datetime import date
    allp = api.get("/api/analytics/overview", params={"range": "all"}).json()
    assert allp["period"]["from"] == "2025-12-28"  # the earliest activity in the fixture (f4 received)
    assert allp["period"]["to"] >= date.today().isoformat()
    year = api.get("/api/analytics/overview", params={"range": "all", "year": 2026}).json()
    assert year["period"] == {"from": "2026-01-01", "to": "2026-12-31"}  # an explicit period wins
    assert allp["metrics"]["received"] >= year["metrics"]["received"] > 0
    assert api.get("/api/analytics/overview", params={"range": "bogus"}).status_code == 422


def test_compare_follows_the_selected_period(api):
    login(api)
    # a selected quarter compares the whole quarter with the previous quarter, not a single month
    q = api.get("/api/analytics/compare", params={"mode": "quarter_vs_prev_quarter", "year": 2026, "quarter": 1,
                                                  "anchor": "2026-01-01"}).json()
    assert q["current"] == {"from": "2026-01-01", "to": "2026-03-31"}
    assert q["previous"] == {"from": "2025-10-01", "to": "2025-12-31"}
    # same period one year earlier, for any selected range
    y = api.get("/api/analytics/compare", params={"mode": "yoy", "year": 2026, "month": 1}).json()
    assert y["current"] == {"from": "2026-01-01", "to": "2026-01-31"}
    assert y["previous"] == {"from": "2025-01-01", "to": "2025-01-31"}
    # filters narrow the comparison too
    c = api.get("/api/analytics/compare", params={"mode": "yoy", "year": 2026, "month": 1, "client_id": 999999}).json()
    assert c["overall"]["received"]["current"] == 0


def test_people_endpoints(api, data):
    login(api)
    ed = api.get("/api/people/editors", params=JAN).json()
    assert {e["name"] for e in ed["editors"]} == {"Ann", "Bob"}
    d = api.get(f"/api/people/editors/{data['ann'].id}", params=JAN).json()
    assert d["editor"]["name"] == "Ann" and d["metrics"]["edited"] == 2
    assert [p["name"] for p in d["by_project"]] == ["P1"]
    qc = api.get("/api/people/qc", params=JAN).json()
    assert [m["name"] for m in qc["members"]] == ["Quin"]
    assert qc["totals"]["qc_pending"] == 1
    assert api.get("/api/people/rework", params=JAN).status_code == 404  # rework is not part of the dashboard
    assert api.get("/api/records/rework", params=JAN).status_code == 404
    assert api.get("/api/people/editors/99999", params=JAN).status_code == 404


def test_escalations_summary_and_tracking(api):
    login(api, "m")
    sm = api.get("/api/escalations/summary", params=JAN).json()
    assert sm["total"] == 1 and sm["open"] == 1
    assert sm["by_root_cause"][0]["name"] == "missed instruction"  # normalised
    row = api.get("/api/escalations", params=JAN).json()["rows"][0]
    r = api.patch(f"/api/escalations/{row['id']}", json={"action_status": "closed",
                                                         "corrective_action": "Retrained"})
    assert r.status_code == 200
    assert api.get("/api/escalations/summary", params=JAN).json()["closed"] == 1
    assert api.patch(f"/api/escalations/{row['id']}", json={"action_status": "bogus"}).status_code == 422
    login(api, "v")
    assert api.patch(f"/api/escalations/{row['id']}", json={"action_status": "open"}).status_code == 403


def test_rework_is_left_out_of_every_analytic(api):
    """The fixture has two rework rows for P1; no endpoint may count them or raise a rework alert."""
    login(api)
    for path in ("/api/analytics/overview", "/api/analytics/compare", "/api/analytics/alerts"):
        assert "rework" not in api.get(path, params=JAN).text.lower(), path
    pts = api.get("/api/analytics/timeseries", params={**JAN, "granularity": "week"}).json()["points"]
    assert all("rework" not in p for p in pts)
    cmp_ = api.get("/api/analytics/compare", params={"mode": "month_vs_prev_month", "anchor": "2026-02-15"}).json()
    assert all("rework" not in p and "rework_growth" not in p["flags"] for p in cmp_["projects"])


# ------------------------------------------------------------------------------ health / sync / admin
def test_data_health_and_meta(api):
    login(api)
    h = api.get("/api/health/data").json()
    checks = {c["key"]: c["count"] for c in h["checks"]}
    assert h["forms_total"] == 7 and checks["missing_edit_status"] == 0
    assert checks["missing_qc_status"] == 0
    meta = api.get("/api/meta/filters").json()
    assert {c["name"] for c in meta["clients"]} == {"ACME"}
    assert {p["name"]: p["qc_applicable"] for p in meta["projects"]} == {"P1": True, "P2": False}
    assert meta["data_range"]["from"] == "2025-12-28"


def test_a_viewer_can_press_sync_now(api, monkeypatch):
    monkeypatch.setattr(sync_runner, "get_source", lambda: InMemorySource([alpha()]))
    login(api, "v")
    assert api.post("/api/sync").status_code == 202
    assert api.get("/api/sync/status").json()["last"]["status"] == "ok"


def test_sync_now_runs_and_reports(api, monkeypatch):
    monkeypatch.setattr(sync_runner, "get_source", lambda: InMemorySource([alpha()]))
    login(api, "m")
    assert api.post("/api/sync").status_code == 202  # background task runs before the client returns
    st = api.get("/api/sync/status").json()
    assert st["running"] is False and st["last"]["status"] == "ok"
    assert st["last"]["files_total"] == 1 and st["last"]["progress_pct"] == 100.0
    assert st["last"]["rows_upserted"] > 0
    assert api.get("/api/health/issues").json()["total"] > 0
    assert len(api.get("/api/sync/logs").json()["logs"]) == 1


def test_documents_and_traceability(api, session, monkeypatch):
    from app.etl.sync import run_sync
    run_sync(session, InMemorySource([alpha()]))
    login(api)
    docs = api.get("/api/documents").json()
    assert docs["total"] == 1 and docs["rows"][0]["forms"] > 0 and docs["rows"][0]["tabs_read"] >= 3
    assert docs["rows"][0]["drive_url"].startswith("https://docs.google.com/spreadsheets/d/")
    d = api.get(f"/api/documents/{docs['rows'][0]['id']}").json()
    tabs = {t["tab"]: t for t in d["tabs"]}
    assert tabs["Login Details"]["kind"] == "ignored" and tabs["Login Details"]["rows_seen"] == 0  # never read
    jan = tabs["January"]
    assert jan["rows_loaded"] + jan["rows_rejected"] + jan["rows_placeholder"] == jan["rows_seen"] - jan["header_row"]
    assert d["summary"]["forms"] == docs["rows"][0]["forms"]
    assert api.get("/api/documents/99999").status_code == 404
    # every record points back to its document, tab and row
    r = api.get("/api/records/forms", params={"date_from": "2020-01-01", "date_to": "2030-01-01",
                                              "columns": "job_id,source_file,source_tab,source_row"}).json()
    synced = [x for x in r["rows"] if x["job_id"] in {"1001", "1002", "2001"}]  # the fixture's hand-made forms have no source
    assert len(synced) == 3 and all(x["source_file"] == "TST_Alpha Shop_Q1 2026" and x["source_tab"] and x["source_row"] for x in synced)


def test_every_tab_is_browsable_and_covered(api, session):
    from app.etl.sync import run_sync
    from tests.test_sync import kept_workbook
    run_sync(session, InMemorySource([kept_workbook()]))
    login(api)
    cov = api.get("/api/documents/coverage").json()
    kinds = {k["kind"]: k for k in cov["kinds"]}
    assert cov["files"] == 1 and cov["tabs"] == 6 and kinds["ignored"]["tabs"] == 1  # only the login tab is unread
    assert kinds["reference"]["tabs"] == 2 and kinds["supplementary"]["tabs"] == 1 and kinds["escalation"]["tabs"] == 1
    assert cov["raw_rows_stored"] == 3 and cov["forms_from_supplementary_tabs"] == 2
    assert cov["tabs_never_read"] == [{"file": "TST_Kept Shop_Q2 2026", "tab": "Login Details"}]

    doc = api.get("/api/documents").json()["rows"][0]
    d = api.get(f"/api/documents/{doc['id']}").json()
    tabs = {t["tab"]: t for t in d["tabs"]}
    assert doc["tabs"] == 6 and doc["tabs_read"] == 5
    assert tabs["Data Entry"]["browsable"] is True and tabs["April"]["browsable"] is False
    rows = api.get(f"/api/documents/{doc['id']}/tabs/{tabs['Data Entry']['id']}/rows").json()
    assert rows["header"] == ["Date", "Store Id", "Invoice #", "Audited Qty"] and rows["total"] == 2
    assert rows["rows"][0] == {"row_no": 2, "cells": ["4/2/2026", "6666", "116496246", "3"]}
    hit = api.get(f"/api/documents/{doc['id']}/tabs/{tabs['Data Entry']['id']}/rows", params={"search": "6667"}).json()
    assert hit["total"] == 1 and hit["rows"][0]["cells"][1] == "6667"
    # a tab id from another document, or an unknown one, is a 404
    assert api.get(f"/api/documents/{doc['id'] + 1}/tabs/{tabs['Data Entry']['id']}/rows").status_code == 404
    assert api.get(f"/api/documents/{doc['id']}/tabs/999999/rows").status_code == 404


def test_admin_users_and_guards(api, data):
    login(api, "a")
    r = api.post("/api/admin/users", json={"email": "new@example.com", "name": "N", "role": "viewer",
                                           "password": "another-long-password"})
    assert r.status_code == 201 and "password" not in r.text
    assert api.post("/api/admin/users", json={"email": "new@example.com", "name": "N", "role": "viewer",
                                              "password": "another-long-password"}).status_code == 409
    assert api.post("/api/admin/users", json={"email": "z@example.com", "name": "N", "role": "root",
                                              "password": "another-long-password"}).status_code == 422
    me = api.get("/api/auth/me").json()["id"]
    assert api.patch(f"/api/admin/users/{me}", json={"role": "viewer"}).status_code == 422  # no self-demotion
    # QC applicability override flows into the metrics
    api.patch(f"/api/admin/projects/{data['p2'].id}", json={"qc_applicable_override": True})
    m = api.get("/api/analytics/overview", params=JAN).json()["metrics"]
    assert m["qc_pending"] == 2  # f7 now counts
    assert api.put("/api/admin/settings/refresh_schedule", json={"interval_minutes": 0}).status_code == 422
    assert api.put("/api/admin/settings/refresh_schedule", json={"interval_minutes": 1}).status_code == 200
    r = api.post("/api/admin/sheet-rules", json={"priority": 5, "pattern": "([", "kind": "ignored"})
    assert r.status_code == 422


# ------------------------------------------------------------------------------ overall-page trends
def test_forms_compare_and_month_drivers_endpoints(api, data):
    assert api.get("/api/analytics/month-drivers").status_code == 401
    assert api.get("/api/analytics/forms-compare").status_code == 401
    login(api)
    r = api.get("/api/analytics/forms-compare", params={"year": 2026, "month": 1})
    assert r.status_code == 200
    projects = {p["project"]: p for p in r.json()["projects"]}
    assert projects["P1"]["received"]["current"] == 5 and projects["P2"]["received"]["current"] == 1
    assert projects["P1"]["forms"][0]["form"] == "F"
    only = api.get("/api/analytics/forms-compare", params={"year": 2026, "month": 1, "project_id": data["p2"].id})
    assert [p["project"] for p in only.json()["projects"]] == ["P2"]
    assert api.get("/api/analytics/forms-compare", params={"vs": "bad"}).status_code == 422

    d = api.get("/api/analytics/month-drivers", params={"year": 2026, "month": 2}).json()
    assert d["metric"] == "received"
    feb = d["months"][0]
    assert feb["month"] == "2026-02-01" and feb["direction"] == "down"  # 6 in Jan -> 0 in Feb
    assert feb["decliners"][0]["project"] == "P1"
    assert api.get("/api/analytics/month-drivers", params={"metric": "nope"}).status_code == 422


def test_forms_months_endpoint(api, data):
    assert api.get("/api/analytics/forms-months").status_code == 401
    login(api)
    r = api.get("/api/analytics/forms-months", params={"year": 2026, "quarter": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["months"][:3] == ["2026-01-01", "2026-02-01", "2026-03-01"]
    assert body["totals"][0] == 6  # same 6 forms received in January as the overview
    p1 = next(p for p in body["projects"] if p["project"] == "P1")
    assert p1["months"][0] == 5 and p1["forms"][0]["form"] == "F"
    assert api.get("/api/analytics/forms-months", params={"metric": "nope"}).status_code == 422


def test_change_drivers_endpoint(api, data):
    q = {"metric": "received", "cur_from": "2026-02-01", "cur_to": "2026-02-28",
         "prev_from": "2026-01-01", "prev_to": "2026-01-31"}
    assert api.get("/api/analytics/change-drivers", params=q).status_code == 401
    login(api)
    r = api.get("/api/analytics/change-drivers", params=q)
    assert r.status_code == 200
    body = r.json()
    assert body["delta"] == body["current"]["total"] - body["previous"]["total"] == -6
    assert body["decliners"][0]["project"] == "P1" and body["decline_total"] == -6
    assert api.get("/api/analytics/change-drivers", params={**q, "metric": "rework"}).status_code == 422
    assert api.get("/api/analytics/change-drivers", params={**q, "cur_from": "2026-03-01"}).status_code == 422


def test_cached_answers_follow_the_data(api, engine):
    """A repeated question is answered from the cache, and a write to the forms empties it at once."""
    from sqlalchemy.orm import Session
    from app.models import Form
    from app.services import cache
    login(api)
    first = api.get("/api/analytics/overview", params=JAN).json()["metrics"]["received"]
    before = cache.hits
    assert api.get("/api/analytics/overview", params=JAN).json()["metrics"]["received"] == first
    assert cache.hits == before + 1
    with Session(engine) as s:  # the TEST database, never the real one
        f = s.query(Form).filter(Form.received_date.between(date(2026, 1, 1), date(2026, 1, 31)), Form.deleted_at.is_(None)).first()
        f.units = (f.units or 1) + 5
        s.commit()
    assert api.get("/api/analytics/overview", params=JAN).json()["metrics"]["received"] == first + 5
