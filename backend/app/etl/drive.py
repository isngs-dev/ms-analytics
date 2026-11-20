"""Google Drive / Sheets reader (read-only).

Layout it understands (matches the real "MSS Input Directory"):
    <root> / <YYYY> / Q<n>_<YYYY> / <Client>_<Project>_Q<n> <YYYY>   (Google Sheet, or .xlsx)
New year / quarter folders and workbooks are discovered automatically on every run.

Auth, in order of preference:
  1. Service account JSON (GOOGLE_SERVICE_ACCOUNT_FILE) - the folder must be shared with its client_email.
  2. OAuth user token (GOOGLE_OAUTH_TOKEN_FILE, created once by scripts/drive_login.py) - reads with the
     permissions of the person who logged in, so nobody has to re-share the folder.
  3. API key (GOOGLE_API_KEY) - only works for items shared "Anyone with the link"; Drive API keys cannot
     read private files. Old-style link-shared folders also need the resource key (DRIVE_ROOT_RESOURCE_KEY).

Only tab *titles* are listed first; the sync decides which tabs to read, so credential tabs
("Login Details") are never fetched.
"""
from __future__ import annotations

import io
import re
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from .discover import parse_quarter_folder, parse_workbook_name
from .sources import FileMeta

SHEET_MIME = "application/vnd.google-apps.spreadsheet"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/spreadsheets.readonly"]
MAX_DEPTH = 4  # root > year > quarter > (optional extra level)
BATCH_TABS = 6  # tabs per Sheets batchGet call
HTTP_TIMEOUT_SECONDS = 120  # per network operation of a Google call


class DriveConfigError(RuntimeError):
    """Credentials / folder id missing or unusable (shown to the admin as-is)."""


class DriveAccessError(RuntimeError):
    pass


class RateLimiter:
    """Sheets read quota is ~60 requests/min/user: stay just under it."""

    def __init__(self, per_minute: int = 55, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.per_minute, self.clock, self.sleep = per_minute, clock, sleep
        self.calls: deque[float] = deque()

    def wait(self) -> None:
        now = self.clock()
        while self.calls and now - self.calls[0] >= 60:
            self.calls.popleft()
        if len(self.calls) >= self.per_minute:
            self.sleep(max(0.0, 60 - (now - self.calls[0])) + 0.05)
        self.calls.append(self.clock())


def _quote_tab(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def _parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class DriveSource:
    def __init__(self, root_id: str, drive: Any, sheets: Any, *, root_resource_key: str = "",
                 identity: str = "the service account", limiter: RateLimiter | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        if not root_id:
            raise DriveConfigError("DRIVE_ROOT_FOLDER_ID is not set")
        self.root_id, self.drive, self.sheets = root_id, drive, sheets
        self.identity = identity
        self.limiter = limiter or RateLimiter()
        self.sleep = sleep
        self._resource_keys = {root_id: root_resource_key} if root_resource_key else {}
        self._mime: dict[str, str] = {}
        self._xlsx_cache: tuple[str, Any] | None = None

    # ------------------------------------------------------------------ construction
    @classmethod
    def from_settings(cls, s) -> "DriveSource":
        import httplib2
        from googleapiclient.discovery import build as _build

        def build(name, version, credentials=None, developerKey=None, cache_discovery=False):
            """Every Google call has a time limit: one request that hangs must not freeze the sync (it holds the run lock,
            so every later automatic sync would silently do nothing)."""
            http = httplib2.Http(timeout=HTTP_TIMEOUT_SECONDS)
            if credentials is not None:
                import google_auth_httplib2
                http = google_auth_httplib2.AuthorizedHttp(credentials, http=http)
                return _build(name, version, http=http, cache_discovery=False)
            return _build(name, version, http=http, developerKey=developerKey, cache_discovery=False)

        key_file = Path(s.google_service_account_file)
        if key_file.is_file():
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_file(str(key_file), scopes=SCOPES)
            drive = build("drive", "v3", credentials=creds, cache_discovery=False)
            sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
            identity = creds.service_account_email
        elif Path(s.google_oauth_token_file).is_file():
            from google.oauth2.credentials import Credentials
            try:
                creds = Credentials.from_authorized_user_file(s.google_oauth_token_file, SCOPES)
            except (ValueError, KeyError) as e:
                raise DriveConfigError(f"{s.google_oauth_token_file} is not a valid OAuth token file ({e}); "
                                       "re-run scripts/drive_login.py") from e
            # the client refreshes the short-lived access token from the stored refresh token on demand
            drive = build("drive", "v3", credentials=creds, cache_discovery=False)
            sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
            identity = "the Google account that ran drive_login.py"
        elif s.google_api_key:
            drive = build("drive", "v3", developerKey=s.google_api_key, cache_discovery=False)
            sheets = build("sheets", "v4", developerKey=s.google_api_key, cache_discovery=False)
            identity = "the API key (public link access only)"
        else:
            raise DriveConfigError(
                "No Google credentials: add a service-account JSON (GOOGLE_SERVICE_ACCOUNT_FILE), an OAuth token "
                "from scripts/drive_login.py (GOOGLE_OAUTH_TOKEN_FILE) or an API key (GOOGLE_API_KEY). "
                "See README, 'Connect Google Drive'")
        return cls(s.drive_root_folder_id, drive, sheets, root_resource_key=s.drive_root_resource_key,
                   identity=identity)

    # ------------------------------------------------------------------ low-level call with throttle + retry
    def _execute(self, request: Any, ids: Iterable[str] = ()) -> Any:
        keys = [f"{i}/{self._resource_keys[i]}" for i in ids if i in self._resource_keys]
        if keys and hasattr(request, "headers"):
            request.headers["X-Goog-Drive-Resource-Keys"] = ",".join(keys)
        from googleapiclient.errors import HttpError

        for attempt in range(6):
            self.limiter.wait()
            try:
                return request.execute()
            except HttpError as e:
                status = getattr(e.resp, "status", 0)
                text = str(e).lower()
                transient = status in (429, 500, 502, 503, 504) or (status == 403 and "ratelimit" in text.replace(" ", ""))
                if transient and attempt < 5:
                    self.sleep(min(60, 2 ** (attempt + 1)))
                    continue
                if status in (403, 404):
                    raise DriveAccessError(
                        f"Google returned {status}. Check that the folder / file is shared with {self.identity} "
                        f"(Viewer is enough) and that the Drive and Sheets APIs are enabled.") from e
                raise

    # ------------------------------------------------------------------ discovery
    def _children(self, folder_id: str) -> Iterator[dict]:
        token = None
        while True:
            req = self.drive.files().list(
                q=f"'{folder_id}' in parents and trashed = false", pageSize=1000, pageToken=token,
                fields="nextPageToken, files(id, name, mimeType, modifiedTime, shortcutDetails(targetId, targetMimeType))",
                supportsAllDrives=True, includeItemsFromAllDrives=True, orderBy="name")
            resp = self._execute(req, ids=[folder_id])
            yield from resp.get("files", [])
            token = resp.get("nextPageToken")
            if not token:
                return

    def list_files(self) -> Iterable[FileMeta]:
        out: list[FileMeta] = []
        self._walk(self.root_id, None, None, 0, out)
        return out

    def _walk(self, folder_id: str, year: int | None, quarter: int | None, depth: int, out: list[FileMeta]):
        for f in self._children(folder_id):
            mime, fid = f["mimeType"], f["id"]
            if mime == SHORTCUT_MIME and f.get("shortcutDetails"):
                mime, fid = f["shortcutDetails"].get("targetMimeType", ""), f["shortcutDetails"]["targetId"]
            name = f["name"]
            if mime == FOLDER_MIME:
                if depth + 1 > MAX_DEPTH:
                    continue
                q = parse_quarter_folder(name)
                y, qn = year, quarter
                if q:
                    qn, y = q
                elif re.fullmatch(r"\d{4}", name.strip()):
                    y = int(name.strip())
                self._walk(fid, y, qn, depth + 1, out)
            elif mime in (SHEET_MIME, XLSX_MIME):
                base = re.sub(r"\.xlsx$", "", name, flags=re.I)
                parsed = parse_workbook_name(base)
                self._mime[fid] = mime
                out.append(FileMeta(fid, base, year or parsed.year, quarter or parsed.quarter,
                                    _parse_time(f["modifiedTime"])))

    # ------------------------------------------------------------------ tabs
    def list_tabs(self, file: FileMeta) -> list[str]:
        if self._mime.get(file.drive_file_id) == XLSX_MIME:
            return list(self._xlsx(file).sheetnames)
        resp = self._execute(self.sheets.spreadsheets().get(
            spreadsheetId=file.drive_file_id, includeGridData=False,
            fields="sheets.properties(title,sheetType)"), ids=[file.drive_file_id])
        return [s["properties"]["title"] for s in resp.get("sheets", [])
                if s["properties"].get("sheetType", "GRID") == "GRID"]

    def read_tabs(self, file: FileMeta, tabs: list[str]) -> dict[str, list[list[Any]]]:
        """One round trip per BATCH_TABS tabs (not one per tab) to stay inside the read quota."""
        if not tabs:
            return {}
        if self._mime.get(file.drive_file_id) == XLSX_MIME:
            wb = self._xlsx(file)
            out_x: dict[str, list[list[Any]]] = {}
            for t in tabs:
                ws = wb[t]
                # a read-only sheet trusts the <dimension> tag, and files written by other tools often declare a
                # smaller range than the data really covers: rows below / columns right of it would silently vanish
                ws.reset_dimensions()
                out_x[t] = [list(r) for r in ws.iter_rows(values_only=True)]
            return out_x
        out: dict[str, list[list[Any]]] = {}
        for i in range(0, len(tabs), BATCH_TABS):
            chunk = tabs[i:i + BATCH_TABS]
            resp = self._execute(self.sheets.spreadsheets().values().batchGet(
                spreadsheetId=file.drive_file_id, ranges=[_quote_tab(t) for t in chunk],
                valueRenderOption="FORMATTED_VALUE", majorDimension="ROWS"), ids=[file.drive_file_id])
            for t, vr in zip(chunk, resp.get("valueRanges", [])):
                out[t] = vr.get("values", [])
        return out

    def read_tab(self, file: FileMeta, tab: str) -> list[list[Any]]:
        return self.read_tabs(file, [tab])[tab]

    def _xlsx(self, file: FileMeta):
        if self._xlsx_cache and self._xlsx_cache[0] == file.drive_file_id:
            return self._xlsx_cache[1]
        from googleapiclient.http import MediaIoBaseDownload
        from openpyxl import load_workbook

        buf = io.BytesIO()
        req = self.drive.files().get_media(fileId=file.drive_file_id, supportsAllDrives=True)
        dl = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            self.limiter.wait()
            _, done = dl.next_chunk()
        buf.seek(0)
        wb = load_workbook(buf, read_only=True, data_only=True)
        self._xlsx_cache = (file.drive_file_id, wb)
        return wb

    # ------------------------------------------------------------------ diagnostics
    def whoami(self) -> str | None:
        """Email of the authenticated user (OAuth / service account); None for plain API keys."""
        try:
            resp = self._execute(self.drive.about().get(fields="user(emailAddress)"))
            return resp.get("user", {}).get("emailAddress")
        except Exception:
            return None

    def root_name(self) -> str:
        resp = self._execute(self.drive.files().get(fileId=self.root_id, fields="id,name",
                                                    supportsAllDrives=True), ids=[self.root_id])
        return resp["name"]
