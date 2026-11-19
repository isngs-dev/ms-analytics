"""Forms-inside-projects comparison and month-by-month drop drivers, on a dataset with known numbers."""
from datetime import date

import pytest

from app.models import DimClient, DimProject, Form
from app.services import trends
from app.services.metrics import overview as metrics_overview
from app.services.scope import Scope

D = date
TODAY = D(2026, 6, 15)


def add(s, client, project, form, month, day, n, edited=False):
    for i in range(n):
        s.add(Form(client_id=client.id, project_id=project.id, job_id=f"{project.name}{form}{month}{day}{i}",
                   received_date=D(2026, month, day), form_name=form,
                   edit_date=D(2026, month, day) if edited else None,
                   edit_status="Edited & Saved" if edited else None, row_hash=f"{project.name}{form}{month}{day}{i}"))


@pytest.fixture()
def world(session):
    s = session
    c = DimClient(name="ACME")
    s.add(c)
    s.flush()
    a, b = DimProject(client_id=c.id, name="A"), DimProject(client_id=c.id, name="B")
    s.add_all([a, b])
    s.flush()
    add(s, c, a, "Alpha", 1, 10, 6)       # Jan: A/Alpha 6, B/Beta 4          = 10
    add(s, c, b, "Beta", 1, 5, 4)
    add(s, c, a, "Alpha", 2, 4, 2)        # Feb: A/Alpha 2, B/Beta 4          = 6   (A/Alpha -4)
    add(s, c, b, "Beta", 2, 5, 4)
    add(s, c, a, "Alpha", 3, 6, 2)        # Mar: A/Alpha 2, B/Beta 1, B/Gamma 5 = 8 (up, but Beta fell -3)
    add(s, c, b, "Beta", 3, 5, 1)
    add(s, c, b, "Gamma", 3, 5, 5, edited=True)
    s.commit()
    return {"a": a, "b": b}


def scope(**kw):
    return Scope(D(2026, 1, 1), D(2026, 3, 31), **kw)


def test_the_month_that_went_down_names_project_and_form(session, world):
    out = trends.month_drivers(session, scope(), "received", today=TODAY)
    jan, feb, mar = out["months"]
    assert (jan["current"], jan["previous"]) == (10, 0)
    assert (feb["current"], feb["previous"], feb["delta"], feb["direction"]) == (6, 10, -4, "down")
    [dec] = feb["decliners"]
    assert (dec["project"], dec["delta"], dec["share_of_decline_pct"]) == ("A", -4, 100.0)
    assert dec["forms"] == [{"form": "Alpha", "current": 2, "previous": 6, "delta": -4}]
    assert feb["gainers"] == []


def test_a_growing_month_still_shows_the_form_that_fell(session, world):
    mar = trends.month_drivers(session, scope(), "received", today=TODAY)["months"][2]
    assert (mar["current"], mar["previous"], mar["direction"]) == (8, 6, "up")
    assert [(p["project"], p["delta"], p["forms"][0]["form"]) for p in mar["decliners"]] == [("B", -3, "Beta")]
    assert [(p["project"], p["delta"], p["forms"][0]["form"]) for p in mar["gainers"]] == [("B", 5, "Gamma")]
    assert mar["decliners"][0]["net_delta"] == 2  # B as a whole grew: +5 Gamma, -3 Beta


def test_drivers_follow_the_filters(session, world):
    only_b = trends.month_drivers(session, scope(project_ids=(world["b"].id,)), "received", today=TODAY)["months"]
    assert [m["current"] for m in only_b] == [4, 4, 6]
    assert only_b[1]["direction"] == "flat" and only_b[1]["decliners"] == []
    edited = trends.month_drivers(session, scope(), "edited", today=TODAY)["months"]
    assert [m["current"] for m in edited] == [0, 0, 5]


def test_month_in_progress_is_compared_like_for_like(session, world):
    s = session
    c = s.query(DimClient).one()
    add(s, c, world["a"], "Alpha", 6, 3, 3)    # June 3: inside the first 15 days
    add(s, c, world["a"], "Alpha", 5, 20, 7)   # May 20: after day 15, must not count against June
    add(s, c, world["a"], "Alpha", 5, 4, 3)    # May 4
    s.commit()
    out = trends.month_drivers(session, Scope(D(2026, 5, 1), D(2026, 6, 30)), "received", today=TODAY)
    may, june = out["months"]
    assert (may["current"], may["previous"]) == (10, 0)
    assert june["partial"] is True
    assert (june["current"], june["previous"]) == (3, 3)  # May 1-15 only
    assert june["direction"] == "flat"


def test_future_months_are_not_listed(session, world):
    out = trends.month_drivers(session, Scope(D(2026, 5, 1), D(2026, 12, 31)), "received", today=TODAY)
    assert [m["month"] for m in out["months"]] == ["2026-05-01", "2026-06-01"]


def test_forms_compare_groups_forms_under_their_project(session, world):
    out = trends.forms_compare(session, Scope(D(2026, 3, 1), D(2026, 3, 31)), "previous", today=TODAY)
    assert out["current"] == {"from": "2026-03-01", "to": "2026-03-31"}
    assert out["previous"] == {"from": "2026-01-29", "to": "2026-02-28"}  # the 31 days before
    proj = {p["project"]: p for p in out["projects"]}
    assert proj["B"]["received"]["current"] == 6 and proj["B"]["received"]["previous"] == 4
    forms = {f["form"]: f for f in proj["B"]["forms"]}
    assert forms["Beta"]["received"]["delta"] == -3 and forms["Beta"]["received"]["direction"] == "down"
    assert forms["Gamma"]["received"]["current"] == 5 and forms["Gamma"]["received"]["previous"] == 0
    assert forms["Gamma"]["edited"]["current"] == 5
    assert proj["A"]["forms"][0]["received"]["pct_change"] == 0.0


def test_forms_compare_year_on_year_and_filter(session, world):
    out = trends.forms_compare(session, Scope(D(2026, 3, 1), D(2026, 3, 31), project_ids=(world["a"].id,)), "yoy",
                               today=TODAY)
    assert out["previous"] == {"from": "2025-03-01", "to": "2025-03-31"}
    assert [p["project"] for p in out["projects"]] == ["A"]
    assert out["projects"][0]["received"]["previous"] == 0


def test_forms_by_month_gives_one_column_per_month(session, world):
    out = trends.forms_by_month(session, scope(), "received", today=TODAY)
    assert out["months"] == ["2026-01-01", "2026-02-01", "2026-03-01"]
    assert out["totals"] == [10, 6, 8] and out["partial_month"] is None
    proj = {p["project"]: p for p in out["projects"]}
    assert proj["A"]["months"] == [6, 2, 2] and proj["B"]["months"] == [4, 4, 6]
    forms = {f["form"]: f for f in proj["B"]["forms"]}
    assert forms["Beta"]["months"] == [4, 4, 1] and forms["Gamma"]["months"] == [0, 0, 5]
    assert out["projects"][0]["project"] == "B"  # 14 forms against A's 10


def test_forms_by_month_follows_filters_and_marks_the_running_month(session, world):
    out = trends.forms_by_month(session, Scope(D(2026, 5, 1), D(2026, 12, 31), project_ids=(world["a"].id,)),
                                "received", today=TODAY)
    assert out["months"] == ["2026-05-01", "2026-06-01"] and out["partial_month"] == "2026-06-01"
    assert out["projects"] == []
    edited = trends.forms_by_month(session, scope(), "edited", today=TODAY)
    assert edited["totals"] == [0, 0, 5]


def test_change_drivers_add_up_to_the_change(session, world):
    out = trends.change_drivers(session, scope(), "received", (D(2026, 3, 1), D(2026, 3, 31)),
                                (D(2026, 2, 1), D(2026, 2, 28)))
    assert (out["current"]["total"], out["previous"]["total"], out["delta"]) == (8, 6, 2)
    assert [(r["project"], r["form"], r["delta"]) for r in out["decliners"]] == [("B", "Beta", -3)]
    assert [(r["project"], r["form"], r["delta"]) for r in out["gainers"]] == [("B", "Gamma", 5)]
    assert out["decline_total"] + out["gain_total"] == out["delta"] == 2  # forms explain the whole change
    drop = trends.change_drivers(session, scope(), "received", (D(2026, 2, 1), D(2026, 2, 28)),
                                 (D(2026, 1, 1), D(2026, 1, 31)))
    assert drop["delta"] == -4 and drop["decliners"][0]["form"] == "Alpha" and drop["gainers"] == []


def test_month_weeks_are_whole_monday_sunday_weeks_owned_by_their_thursday():
    jan = trends.month_weeks(D(2026, 1, 1))
    assert jan == [D(2025, 12, 29), D(2026, 1, 5), D(2026, 1, 12), D(2026, 1, 19), D(2026, 1, 26)]
    assert all(m.weekday() == 0 for m in jan)
    assert trends.month_weeks(D(2026, 10, 1))[0] == D(2026, 9, 28)  # Thursday 1 Oct
    assert D(2026, 9, 28) not in trends.month_weeks(D(2026, 9, 1))  # never in two months


def test_week_grid_counts_every_day_including_an_empty_sunday(session, world):
    out = trends.week_grid(session, scope(), "received", today=TODAY)
    jan = out["months"][0]
    assert [w["no"] for w in jan["weeks"]] == [1, 2, 3, 4, 5]
    w2 = jan["weeks"][1]
    assert (w2["from"], w2["to"], w2["total"]) == ("2026-01-05", "2026-01-11", 10)
    assert [d["weekday"] for d in w2["days"]] == list(trends.WEEKDAYS)
    assert [d["n"] for d in w2["days"]] == [4, 0, 0, 0, 0, 6, 0]  # Mon Beta 4, Sat Alpha 6, Sunday 0 still a day
    assert w2["days_counted"] == 7 and w2["avg_per_day"] == round(10 / 7, 1)
    assert out["total"] == 24 and sum(m["total"] for m in out["months"]) == 24


def test_week_grid_compares_with_the_same_week_of_the_month_before(session, world):
    out = trends.week_grid(session, scope(), "received", today=TODAY)
    feb = out["months"][1]
    assert [w["no"] for w in feb["weeks"]] == [1, 2, 3, 4]
    w1, w2 = feb["weeks"][0], feb["weeks"][1]
    assert w1["total"] == 6 and w2["total"] == 0
    same = w2["vs_same_week_last_month"]  # Feb 9-15 against Jan 5-11
    assert (same["prev"], same["cur"]) == (["2026-01-05", "2026-01-11"], ["2026-02-09", "2026-02-15"])
    assert (same["current"], same["previous"], same["delta"], same["direction"]) == (0, 10, -10, "down")
    prev_wk = w1["vs_previous_week"]
    assert prev_wk["prev"] == ["2026-01-26", "2026-02-01"] and prev_wk["current"] == 6
    jan5 = out["months"][0]["weeks"][4]
    assert jan5["vs_same_week_last_month"] is None and jan5["same_week_last_month_missing"] is True
    assert feb["vs_previous_month"]["previous"] == 10 + 0 and feb["vs_previous_month"]["current"] == 6


def test_week_grid_follows_filters_and_the_running_week_is_like_for_like(session, world):
    only_b = trends.week_grid(session, scope(project_ids=(world["b"].id,)), "received", today=TODAY)
    assert only_b["months"][0]["weeks"][1]["total"] == 4
    s = session
    c = s.query(DimClient).one()
    add(s, c, world["a"], "Alpha", 6, 15, 2)   # Monday 15 June = today
    add(s, c, world["a"], "Alpha", 6, 8, 5)    # Monday 8 June
    add(s, c, world["a"], "Alpha", 6, 12, 9)   # Friday 12 June: after day one of the week, must not count
    s.commit()
    out = trends.week_grid(session, Scope(D(2026, 6, 1), D(2026, 6, 30)), "received", today=TODAY)
    wk = [w for w in out["months"][0]["weeks"] if w["from"] == "2026-06-15"][0]
    assert wk["running"] is True and wk["total"] == 2 and wk["days_counted"] == 1
    assert [d["future"] for d in wk["days"]] == [False] + [True] * 6 and wk["days"][1]["n"] is None
    assert wk["vs_previous_week"]["prev"] == ["2026-06-08", "2026-06-08"]
    assert (wk["vs_previous_week"]["current"], wk["vs_previous_week"]["previous"]) == (2, 5)


def test_change_drivers_respect_filters_and_limit(session, world):
    only_a = trends.change_drivers(session, scope(project_ids=(world["a"].id,)), "received",
                                   (D(2026, 2, 1), D(2026, 2, 28)), (D(2026, 1, 1), D(2026, 1, 31)))
    assert only_a["delta"] == -4 and {r["project"] for r in only_a["decliners"]} == {"A"}
    one = trends.change_drivers(session, scope(), "received", (D(2026, 3, 1), D(2026, 3, 31)),
                                (D(2026, 1, 1), D(2026, 1, 31)), limit=1)
    assert len(one["decliners"]) == 1 and one["decliner_count"] == 2  # A/Alpha and B/Beta both fell vs January


def test_image_counted_project_adds_its_images_not_its_rows(session):
    from app.etl.loader import image_units
    from app.services import metrics
    assert image_units({"#images": "14.0"}) == 14 and image_units({"#Images": "0"}) == 0
    assert image_units({}) == 1 and image_units({"#images": "n/a"}) == 1  # unreadable: the row still counts
    s = session
    c = DimClient(name="IS")
    s.add(c)
    s.flush()
    p = DimProject(client_id=c.id, name="Global Data")
    s.add(p)
    s.flush()
    for i, n in enumerate((14, 23, 0)):
        s.add(Form(client_id=c.id, project_id=p.id, job_id=f"G{i}", received_date=D(2026, 3, 4), form_name="Photos",
                   edit_date=D(2026, 3, 5), edit_status="Finalized", units=n, row_hash=f"g{i}"))
    s.commit()
    sc = Scope(D(2026, 3, 1), D(2026, 3, 31))
    m = metrics.overview(s, sc)
    assert (m["received"], m["finalised"], m["processed"]) == (37, 37, 37)  # 3 rows, 37 images
    assert (m["received_handled"], m["received_pending"]) == (37, 0)
    pts = {r["bucket"]: r for r in metrics.timeseries(s, sc, "day")}
    assert pts["2026-03-04"]["received"] == 37 and pts["2026-03-05"]["finalised"] == 37
    out = trends.week_grid(s, sc, "received", today=TODAY)
    assert out["total"] == 37
    assert trends.change_drivers(s, sc, "received", (D(2026, 3, 1), D(2026, 3, 31)),
                                 (D(2026, 2, 1), D(2026, 2, 28)))["gainers"][0]["delta"] == 37


def test_received_splits_into_handled_and_still_pending(session, world):
    m = metrics_overview(session, Scope(D(2026, 3, 1), D(2026, 3, 31)))
    assert m["received"] == 8 and m["received_handled"] == 5 and m["received_pending"] == 3  # Gamma's 5 are edited
    assert m["received_handled"] + m["received_pending"] == m["received"]
    jan = metrics_overview(session, Scope(D(2026, 1, 1), D(2026, 1, 31)))
    assert (jan["received"], jan["received_handled"], jan["received_pending"]) == (10, 0, 10)


# ------------------------------------------------------------------------------ the compared ranges are stated, not implied
def test_month_drivers_state_the_exact_ranges_compared(session, world):
    out = trends.month_drivers(session, scope(), "received", today=TODAY)
    jan, feb, mar = out["months"]
    assert feb["current_range"] == ["2026-02-01", "2026-02-28"]
    assert feb["previous_range"] == ["2026-01-01", "2026-01-31"]
    assert mar["previous_range"] == ["2026-02-01", "2026-02-28"]
    assert jan["previous_range"] == ["2025-12-01", "2025-12-31"]


def test_month_in_progress_ranges_are_cut_to_the_same_days(session, world):
    out = trends.month_drivers(session, Scope(D(2026, 5, 1), D(2026, 6, 30)), "received", today=TODAY)
    may, june = out["months"]
    assert may["current_range"] == ["2026-05-01", "2026-05-31"]
    assert june["partial"] is True
    assert june["current_range"] == ["2026-06-01", "2026-06-15"]   # up to today
    assert june["previous_range"] == ["2026-05-01", "2026-05-15"]  # the same number of days
