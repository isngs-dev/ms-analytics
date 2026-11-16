"""DriveSource against a fake Drive/Sheets service (no network, no credentials)."""
import pytest

from app.etl.drive import DriveSource, RateLimiter, DriveAccessError, _quote_tab
from app.etl.sync import run_sync
from tests.test_sync import HEADER, row

FOLDER = "application/vnd.google-apps.folder"
SHEET = "application/vnd.google-apps.spreadsheet"


class Req:
    def __init__(self, fn):
        self.fn, self.headers = fn, {}

    def execute(self):
        return self.fn()


class FakeDrive:
    """tree: folder id -> list of child dicts. Pages of 2 to exercise pagination."""

    def __init__(self, tree):
        self.tree, self.list_calls, self.headers_seen = tree, 0, []

    def files(self):
        return self

    def list(self, q, pageSize, pageToken, fields, **kw):
        parent = q.split("'")[1]
        kids = self.tree.get(parent, [])
        start = int(pageToken or 0)
        page = kids[start:start + 2]
        nxt = str(start + 2) if start + 2 < len(kids) else None

        def run():
            self.list_calls += 1
            return {"files": page, **({"nextPageToken": nxt} if nxt else {})}
        r = Req(run)
        self.headers_seen.append(r)
        return r

    def get(self, fileId, fields, **kw):
        return Req(lambda: {"id": fileId, "name": "MSS Input Directory"})


class FakeSheets:
    def __init__(self, books):
        self.books, self.batch_calls, self.requested = books, 0, []

    def spreadsheets(self):
        return self

    def get(self, spreadsheetId, **kw):
        tabs = self.books[spreadsheetId]
        return Req(lambda: {"sheets": [{"properties": {"title": t, "sheetType": "GRID"}} for t in tabs]})

    def values(self):
        return self

    def batchGet(self, spreadsheetId, ranges, **kw):
        def run():
            self.batch_calls += 1
            self.requested.extend(ranges)
            return {"valueRanges": [{"values": self.books[spreadsheetId][r.strip("'").replace("''", "'")]} for r in ranges]}
        return Req(run)


def f(id_, name, mime=SHEET, modified="2026-03-01T10:00:00.000Z"):
    return {"id": id_, "name": name, "mimeType": mime, "modifiedTime": modified}


@pytest.fixture()
def fake():
    tree = {
        "root": [f("y24", "2024", FOLDER), f("y26", "2026", FOLDER), f("n1", "notes.pdf", "application/pdf"),
                 f("trash", "Misc", FOLDER)],
        "y24": [f("q1_24", "Q1_2024", FOLDER)],
        "y26": [f("q1_26", "Q1_2026", FOLDER), f("q2_26", "Q2_2026", FOLDER)],
        "q1_24": [f("w1", "TST_Alpha Shop_Q1 2024")],
        "q1_26": [f("w2", "TST_Alpha Shop_Q1 2026"), f("w3", "CXE_Q1 2026"), f("w4", "HSB_Multi-Projects_Q1 2026")],
        "q2_26": [f("w5", "TST_Alpha Shop_Q2 2026.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                  f("d", "diagram", "application/vnd.google-apps.drawing")],
    }
    jan = [HEADER, row("1/2/2026", "Alpha: Visit", "1001", "1/2/2026", "Finalized")]
    books = {
        "w1": {"January": [HEADER]}, "w3": {"January": jan, "Login Details": [["Password", "SECRET"]]},
        "w2": {"January": jan, "Login Details": [["Password", "SECRET"]], "PT January": [["x"]]},
        "w4": {"January": jan},
    }
    return FakeDrive(tree), FakeSheets(books)


def src(fake, **kw):
    d, s = fake
    return DriveSource("root", d, s, limiter=RateLimiter(10_000), sleep=lambda _: None, **kw)


def test_walks_year_and_quarter_folders_with_pagination(fake):
    files = {m.drive_file_id: m for m in src(fake).list_files()}
    assert set(files) == {"w1", "w2", "w3", "w4", "w5"}  # pdf / drawing / empty 'Misc' ignored
    assert (files["w1"].year, files["w1"].quarter) == (2024, 1)
    assert (files["w2"].year, files["w2"].quarter) == (2026, 1)
    assert (files["w5"].year, files["w5"].quarter) == (2026, 2)
    assert files["w5"].name == "TST_Alpha Shop_Q2 2026"  # .xlsx extension stripped
    assert files["w2"].modified_time.isoformat().startswith("2026-03-01T10:00")
    assert fake[0].list_calls >= 5  # 4 root children paginated in pages of 2, plus sub-folders


def test_tabs_and_batched_read_only_for_requested_tabs(fake):
    s = src(fake)
    meta = next(m for m in s.list_files() if m.drive_file_id == "w2")
    assert set(s.list_tabs(meta)) == {"January", "Login Details", "PT January"}
    got = s.read_tabs(meta, ["January"])  # the sync passes only tabs it decided to read
    assert list(got) == ["January"] and got["January"][0] == HEADER
    assert fake[1].requested == ["'January'"] and fake[1].batch_calls == 1


def test_tab_title_quoting():
    assert _quote_tab("Bob's tab") == "'Bob''s tab'"


def test_full_sync_through_drive_source_never_reads_credentials(session, fake):
    s = src(fake)
    s.list_files()  # populate mime map like a real run does
    # xlsx workbook (w5) has no fake content; drop it for this end-to-end check
    fake[0].tree["q2_26"] = []
    log = run_sync(session, s)
    assert log.status == "ok" and log.files_total == 4
    assert all("Login" not in r for r in fake[1].requested)  # credential tab never requested
    assert any("PT " in r for r in fake[1].requested)  # pivots are read now (kept as raw rows); only logins never
    from app.models import Form
    from sqlalchemy import func, select
    assert session.scalar(select(func.count()).select_from(Form)) >= 3


def test_rate_limiter_blocks_when_over_budget():
    t, slept = [0.0], []
    lim = RateLimiter(2, clock=lambda: t[0], sleep=lambda s: (slept.append(s), t.__setitem__(0, t[0] + s)))
    lim.wait(); lim.wait(); lim.wait()  # third call must wait for the window to free up
    assert slept and slept[0] > 59


def test_permission_error_is_explained():
    from googleapiclient.errors import HttpError

    class Resp:
        status = 404
        reason = "Not Found"

    class Bad:
        headers = {}

        def execute(self):
            raise HttpError(Resp(), b"not found")

    class D:
        def files(self): return self
        def get(self, **kw): return Bad()

    s = DriveSource("root", D(), None, identity="svc@x.iam.gserviceaccount.com", limiter=RateLimiter(1000), sleep=lambda _: None)
    with pytest.raises(DriveAccessError) as e:
        s.root_name()
    assert "shared with svc@x.iam.gserviceaccount.com" in str(e.value)


class _S:
    def __init__(self, **kw):
        self.google_service_account_file = kw.get("sa", "/nonexistent/sa.json")
        self.google_oauth_token_file = kw.get("oauth", "/nonexistent/oauth.json")
        self.google_api_key = kw.get("key", "")
        self.drive_root_folder_id = "root"
        self.drive_root_resource_key = ""


def test_credential_selection(tmp_path):
    import json
    from app.etl.drive import DriveConfigError

    with pytest.raises(DriveConfigError) as e:
        DriveSource.from_settings(_S())
    assert "drive_login.py" in str(e.value)  # tells the user the three ways to authenticate

    tok = tmp_path / "oauth.json"
    tok.write_text(json.dumps({"type": "authorized_user", "client_id": "cid", "client_secret": "cs",
                               "refresh_token": "rt", "token_uri": "https://oauth2.googleapis.com/token"}))
    s = DriveSource.from_settings(_S(oauth=str(tok)))
    assert "drive_login" in s.identity

    assert "API key" in DriveSource.from_settings(_S(key="AIza-dummy")).identity

    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    with pytest.raises(DriveConfigError):
        DriveSource.from_settings(_S(oauth=str(bad)))


def test_resource_key_header_is_attached(fake):
    s = src(fake, root_resource_key="0-abc")
    list(s.list_files())
    first = fake[0].headers_seen[0]
    assert first.headers["X-Goog-Drive-Resource-Keys"] == "root/0-abc"
