"""Only the kept years (AppSetting 'sync_years') are offered anywhere: the year dropdown and 'all years' stop at the
first kept year, even when a kept workbook holds a few rows dated earlier (a 2026 sheet with last year's Input Date)."""
from datetime import date

from sqlalchemy.orm import Session

from app.models import AppSetting
from tests.test_api import api, data, login  # noqa: F401  (fixtures)


def keep(engine, years):
    with Session(engine) as s:
        s.add(AppSetting(key="sync_years", value={"years": years}))
        s.commit()


def test_without_a_setting_every_year_in_the_data_is_offered(api):
    login(api)
    assert api.get("/api/meta/filters").json()["data_range"]["from"] == "2025-12-28"


def test_filter_range_starts_at_the_first_kept_year(api, engine):
    login(api)
    keep(engine, [2026])
    meta = api.get("/api/meta/filters").json()
    assert meta["data_range"]["from"] == "2026-01-01"  # f4 was received on 2025-12-28 but sits in a 2026 workbook


def test_all_years_never_reaches_before_the_first_kept_year(api, engine):
    login(api)
    keep(engine, [2026])
    period = api.get("/api/analytics/overview", params={"range": "all"}).json()["period"]
    assert period["from"] == "2026-01-01"


def test_several_kept_years_start_at_the_earliest(api, engine):
    login(api)
    keep(engine, [2025, 2026])
    assert api.get("/api/meta/filters").json()["data_range"]["from"] == "2025-12-28"  # data starts after Jan 1 2025


def test_an_explicit_year_is_not_changed(api, engine):
    login(api)
    keep(engine, [2026])
    period = api.get("/api/analytics/overview", params={"year": 2026, "month": 1}).json()["period"]
    assert (period["from"], period["to"]) == (date(2026, 1, 1).isoformat(), date(2026, 1, 31).isoformat())


def test_each_year_offers_only_its_own_clients_projects_and_people(api, engine):
    """Pick 2025 and only 2025's names are offered, pick 2026 and only 2026's (nobody from the other year)."""
    from app.models import DimClient, DimPerson, DimProject, Form
    with Session(engine) as s:
        old_c = DimClient(name="OldClient")
        s.add(old_c)
        s.flush()
        old_p = DimProject(client_id=old_c.id, name="OldProject")
        gone = DimPerson(name="Gone Editor")
        s.add_all([old_p, gone])
        s.flush()
        s.add(Form(client_id=old_c.id, project_id=old_p.id, job_id="old1", received_date=date(2025, 6, 2),
                   edit_date=date(2025, 6, 3), qc_date=date(2025, 6, 4), editor_id=gone.id, qc_member_id=gone.id,
                   row_hash="old1"))
        s.commit()
    login(api)
    names = lambda m, k: [x["name"] for x in m[k]]  # noqa: E731
    y25 = api.get("/api/meta/filters", params={"year": 2025}).json()
    assert "Gone Editor" in names(y25, "editors") + names(y25, "qc_members")
    assert "OldClient" in names(y25, "clients") and "OldProject" in names(y25, "projects")
    assert "Ann" not in names(y25, "editors")  # Ann only works in 2026
    y26 = api.get("/api/meta/filters", params={"year": 2026}).json()
    assert "Gone Editor" not in names(y26, "editors") + names(y26, "qc_members")
    assert "OldClient" not in names(y26, "clients") and "OldProject" not in names(y26, "projects")
    assert "ACME" in names(y26, "clients") and "Ann" in names(y26, "editors")
    allyears = api.get("/api/meta/filters", params={"range": "all"}).json()
    assert "OldClient" in names(allyears, "clients") and "ACME" in names(allyears, "clients")


def test_with_no_period_the_whole_current_year_is_shown(api):
    login(api)
    year = date.today().year
    p = api.get("/api/analytics/overview").json()["period"]
    assert (p["from"], p["to"]) == (f"{year}-01-01", f"{year}-12-31")


def test_a_new_year_in_drive_is_kept_automatically():
    from app.etl.sync import kept_year
    assert kept_year(2027, [2025, 2026]) and kept_year(2026, [2025, 2026]) and kept_year(None, [2026])
    assert not kept_year(2024, [2025, 2026]) and kept_year(2024, [])
