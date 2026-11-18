# MS Analytics Dashboard

Mystery-shopping operations analytics: forms received, edited, QC'd and escalated, per client,
project, editor and QC member. Data comes from the Google Drive folder **MSS Input Directory**
(`Year / Q1_2026 / Client_Project_Q1 2026` Google Sheets) and is synced automatically.

| Layer | Tech |
|---|---|
| Frontend | Next.js 15 (App Router), TypeScript, Tailwind, TanStack Query / Table, Zustand, ECharts, three.js (react-three-fiber), framer-motion |
| API | FastAPI, SQLAlchemy 2, Alembic, APScheduler |
| Data | PostgreSQL 16 |
| Sync | Google Drive + Sheets APIs (service account, OAuth user token, or API key) |

## Quick start (development)

Requirements: Docker Desktop, Node 20+.

```bash
cp .env.example .env                                        # then edit secrets, see "Configuration"
docker compose up -d                                        # db + api (hot reload) -> http://localhost:8020/docs
docker compose run --rm api python -m app.seed.users        # admin / manager / viewer @example.com, password = DEMO_USER_PASSWORD
docker compose run --rm api python -m app.seed.mock --reset # ~3.5 min: 3 years of synthetic data (mock mode only)
cd frontend && npm install && npm run dev                   # http://localhost:3000
```

**Demo logins** (local only): `admin@example.com`, `manager@example.com`, `viewer@example.com`, password = `DEMO_USER_PASSWORD`
from `.env` (default `change-me-demo-password`). `frontend/.env.local` (`NEXT_PUBLIC_DEMO_LOGINS=1`, `NEXT_PUBLIC_DEMO_PASSWORD=...`)
makes the sign-in page list these accounts with a click-to-fill button. Delete that file before sharing the site, and change the passwords.

Run the tests (they use a separate `ms_analytics_test` database): `docker compose run --rm api python -m pytest -q`

> On some Windows machines application-control policy blocks the Postgres driver on the host. That is why
> Python commands run inside the `api` container.

## Connect Google Drive (auto-sync)

The sync discovers new year / quarter folders and workbooks by itself, re-reads only files whose Drive
`modifiedTime` changed, and never fetches `Login Details`, pivot or email tabs. Pick **one** way to authenticate
(checked in this order):

**A. Service account** (best for servers)
1. Google Cloud console: create a project, enable **Google Drive API** and **Google Sheets API**.
2. IAM > Service accounts > create one > Keys > Add key > JSON. Save it as `secrets/service-account.json`.
3. Have the folder owner share the root folder with the account's `client_email` as **Viewer**.

**B. OAuth with your own Google account** (no re-sharing needed; works with whatever your account can open)
1. Same project and APIs as above. OAuth consent screen: choose **Internal** if your Workspace allows it (no Google review).
   Credentials > Create credentials > OAuth client ID > **Desktop app** > download `client_secret.json`.
2. On your own computer (opens a browser):
   ```bash
   pip install google-auth-oauthlib
   python scripts/drive_login.py --client-secret path/to/client_secret.json
   ```
   This writes `secrets/oauth-token.json` (read-only scopes, git-ignored). Revoke any time at
   https://myaccount.google.com/permissions.

**C. API key** (`GOOGLE_API_KEY`). Google API keys can only read items shared "Anyone with the link". The
current folder is private (quarter folders are domain-only), so this will **not** work for it.

Then verify and switch on:
```bash
docker compose run --rm api python -m app.etl.drive_check     # lists folders / tabs, reads no cell data, writes nothing
# in .env: DATA_SOURCE=drive  and  SCHEDULER_ENABLED=true
docker compose up -d --force-recreate api
```
With `SCHEDULER_ENABLED=true` Drive is checked **every 10 minutes** (Admin > Settings changes the interval) and once
shortly after the API starts; anything uploaded, edited, added in a new quarter folder, moved or deleted in Drive reaches
the dashboard on the next check. Only files whose Drive `modifiedTime` changed are re-read (a check with nothing new
costs a few folder listings and writes no history row). Workbooks that disappear from Drive are removed from the
analytics (with a guard: if the listing suddenly shows under half of the known files nothing is removed). The browser
polls the sync state and refreshes every page by itself when new data lands (header chip: "Live · checked 3 min ago").
Google Drive "push" notifications would need a public HTTPS webhook, so polling is used. You can also use **Sync now**
on the Data Health page. The first full sync makes about two Google calls per workbook and is throttled under Google's read quota,
so expect several minutes for ~160 workbooks; later runs touch only changed files.

After the first real sync open **Data Health**: unmapped columns / statuses are listed there and can be mapped in
**Admin** (column map, status map, sheet rules) without code changes; use **Full re-sync** to apply new mappings to
files already loaded.

## Precision and traceability
All analytics are computed live from the PostgreSQL tables, never from cached or approximate figures, and every figure
can be traced back:
- **Drive Documents** page: every workbook found, its tabs (read / ignored / why), and a per-tab reconciliation:
  rows below the header = blank/template rows + loaded rows + rejected rows (repeat Job IDs merged are shown too).
- Every KPI, chart slice and bar opens the exact records behind it (same rules as the count).
- **Data Explorer** has `source_file`, `source_tab` and `source_row` columns, so each record points to its Drive document,
  tab and spreadsheet row; a document's page links to all of its records.
- Rows that cannot be trusted (no Job ID, a sentence in the Job ID column, unparseable date) are never guessed: they are
  rejected or left blank and listed under Data Health with the file, tab and row.

### Every tab and column is kept
- **Every tab of every workbook is read**, except tabs whose name looks like credentials (`Login Details`), which are
  never fetched and cannot be switched on by a sheet rule.
- Month tabs and `Escalation` tabs load into the analytics tables. `RW` / `Rework` tabs are still read and kept, but
  **rework is not part of any analytic** (no counts, charts, alerts or quality figure use it).
- Any other tab is judged by its header and data: a **form-like tab** (`Incomplete`, `Detail…`, `Copy of …`) adds only the
  Job IDs the main tabs do not have (it never overwrites a real row); a **client-feedback register** (Job Id + Feedback
  Details …) loads as escalation / feedback rows; everything else (`Data Entry`, `Updates`, `Bulk data`, e-mail
  templates, pivots, `Master` lists …) is stored row by row exactly as written (`src_record`) and can be browsed and
  searched from the Drive Documents page (open a document, then **View rows**).
- Input Date columns with a misspelt or junk header (`Inpute Date`, `VIEW`, `kya` …) are recognised from their date
  values; every column that is not part of the standard schema is kept with the record (Data Explorer → Columns →
  *Other columns*, listed under Data Health → *Source columns kept as extra data*).
- `python scripts/audit_drive.py` scans every tab and reports what is / is not loaded; `python scripts/audit_parity.py`
  compares every form row of every workbook with the database field by field (see the docstrings).

## Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | database credentials (change the password outside development) |
| `JWT_SECRET` | signs session tokens, **32+ random characters**; the API refuses to start in `ENVIRONMENT=production` with the default |
| `ENVIRONMENT` | `development` or `production` |
| `COOKIE_SECURE` | `true` when served over HTTPS |
| `CORS_ORIGINS` | only needed if the browser calls the API on a different origin (normally it does not; `/api` is proxied) |
| `DATA_SOURCE` | `mock` (seeded data) or `drive` |
| `GOOGLE_SERVICE_ACCOUNT_FILE`, `GOOGLE_OAUTH_TOKEN_FILE`, `GOOGLE_API_KEY` | Drive credentials, see above |
| `DRIVE_ROOT_FOLDER_ID`, `DRIVE_ROOT_RESOURCE_KEY` | the folder to sync (`resourcekey=` value from an old-style link) |
| `SCHEDULER_ENABLED`, `SYNC_INTERVAL_MINUTES` | automatic Drive check (default every 10 minutes) |
| `DEMO_USER_PASSWORD` | used only by `app.seed.users` for local demo accounts |

## Deployment (Docker Compose)

```bash
cp .env.example .env     # set ENVIRONMENT=production, strong JWT_SECRET and POSTGRES_PASSWORD, COOKIE_SECURE=true behind HTTPS
mkdir -p secrets         # drop the Google credential file here
docker compose -f docker-compose.yml up -d --build
docker compose -f docker-compose.yml exec api python -m app.etl.drive_check
```
`-f docker-compose.yml` skips the development override. The stack is `db` + `api` (runs migrations on start, non-root,
single worker because the scheduler runs in-process) + `web` on port 3000, which proxies `/api/*` to the API so the
session cookie stays same-origin. Put a TLS reverse proxy (Caddy, nginx, a cloud load balancer) in front of `web`.
Create real users from **Admin > Users** (create the first admin with `python -m app.seed.users` and change or
deactivate the demo accounts immediately). Back up the `pgdata` volume.

## Render
A ready-made Blueprint (`render.yaml`) and a step-by-step guide are in [docs/DEPLOY_RENDER.md](docs/DEPLOY_RENDER.md).

## Security notes
- Session is an httpOnly cookie (also accepts a Bearer token); roles are read from the database on every request,
  so deactivating a user takes effect immediately. Passwords are PBKDF2-SHA256; login is rate limited per process.
- Google credentials are read-only scoped and live in `secrets/` (git-ignored, mounted read-only into the API).
- Several workbooks contain `Login Details` tabs with plaintext usernames and passwords. The sync never fetches them,
  but those credentials should be moved to a password manager and rotated.
- Responses carry `nosniff`, frame-deny, referrer and permissions headers.

## What the numbers mean
Counts are event-based: each uses its own date, never the form's current status. See the definitions returned by
`/api/analytics/overview`.

- **Received**: Input Date in period. **Edited**: Transaction Date in period and Ops Status counts as edited
  (default: only *Edited & Saved*, changeable in Admin > Status map). **Finalised**: every form handled in the period (Transaction Date in period, any status), so it lines up with Received.
  **Global Data counts images, not rows**: each row of the Global Data sheet is one shop with N photos, and the `#images` cell is its form count, so every volume (received, edited, finalised, QC, pending) is the sum of `#images` (`forms.units`). Other projects are 1 per row. Override the list with AppSetting `image_count_projects` = `{"projects": ["Global Data", ...]}`; a blank `#images` cell counts as 1.
- **QC completed**: QC Date in period. **Pending editing / QC pending**: evaluated *as of the period end*, so history
  shows what was pending then. QC only applies to projects that have QC data (Admin can override per project).
- **Escalations**: the `Escalation` tab, with action status / owner tracked in the app. **Rework is deliberately left
  out of every figure**; feedback quality = edited reports without a client escalation ÷ edited reports.
- Form identity is (client, project, Job ID); Shop ID and Job ID are the same value.
- Comparisons (week, month, quarter, year) compare an unfinished period like-for-like; alerts flag falling volume
  and growing pending editing.

## Project layout
```
backend/app/etl        discovery, header mapping, loader, Drive reader, sync orchestration
backend/app/services   metrics, comparisons, drill-through records
backend/app/api        FastAPI routers (analytics, people, escalations, records, health, sync, admin, auth)
backend/app/seed       mapping seeds, users, synthetic data generator
backend/migrations     Alembic migrations
frontend/src           Next.js app (pages, 2D charts, 3D scenes, filter store)
docs/PHASE1_SCHEMA.md  canonical schema and mapping decisions
```

## 3D accents
3D is an accent; anything a person must read precisely stays 2D. Overall has floating KPI tiles (mouse parallax,
click for records) and rotating donuts; Clients & Projects has a 3D bar city with a 2D toggle and a camera that flies
Overall > Client > Project > Editor. 3D falls back to 2D automatically without WebGL, with reduced motion / data saver,
on low-end devices, on errors or low frame rate; the top-bar button cycles Auto / 3D / 2D. three.js loads only when a
3D view is shown, pixel ratio is capped at 1.5, and scenes pause off-screen.
