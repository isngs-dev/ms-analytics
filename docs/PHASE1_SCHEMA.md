# Phase 1 – Canonical schema (DRAFT v2, not yet migrated)

Status: revised after inspecting real workbook headers (6 workbooks, one per client family).
No tables exist yet. Open questions are at the bottom.

## What the real data looks like (observed)

Drive: `MSS Input Directory / <Year> / Q<n>_<Year> / <Client>_<Project>_Q<n> <Year>` (native Google Sheets).

Tabs seen in a workbook and how they are classified:

| Tab | Kind | Notes |
|---|---|---|
| `January` … `December` | operational | One row per form. Many months are empty templates whose rows only carry pre-filled Client Name / Error Category / Platform, so a row is valid only if it has a Shop ID. |
| `RW` | rework | One row per re-edit event; the same Shop/Job ID repeats with a new Transaction Date and status. |
| `Escalation` | escalation | Input Date, Shop ID, Editor, Editor name, QC Member, QC Date, Feedback / Client Escalation, Root Cause, Preventive Action, Remarks. |
| `Master` | master | Lookup lists only (statuses, error categories, hold reasons, editor names). Never counted. |
| `Incomplete` (HSB) | operational (historical) | Same columns as monthly tabs plus `Incomplete Status`. |
| `Query to Client` (Confero) | client_query | Shop ID, Query, Shop Date, First Status, Second Status. Out of scope unless you say otherwise. |
| `PT <Month>`, `Pivot Table n` | ignored | Pivot summaries; would double-count. |
| `Update`, `s email`, `Email Sample to shoppers` | ignored | Notes / email templates. |
| `Login Details` / `Login details` | **ignored, never read** | Contains plaintext credentials. See the security note below. |

Operational columns (header text varies slightly between workbooks):
`Input Date`, `Form`, `Class / Location` (or `Location`), `Shop ID`, `Shop Date`, `Input Status`,
`Editor` (= editor *type*: iSN Team / Freelancer), `Editor Name` (= the person),
`Transaction Date` (also spelled `Transation Date`), `Ops Status` / `OPS Status`,
`Comments to shopper`, `Hold/Incomplete Category`, `QC Member`, `QC Date`, `QC Status` (header
blank in some sheets), `Feedback`, `Client Name`, `Client Escalation`, `Company's Name` /
`Company Name`, `Error Category`, `Platform`, plus an unnamed counter column (always 1) and
sometimes `Incomplete Status`.

Variations the mapper must absorb: case (`Input date`), typos, a blank `Input Date` header,
blank `QC Status` header, mixed date formats (`1/2/2026`, `01/21/26`, `12/29/25`), trailing
spaces in IDs, `Job ID` instead of `Shop ID` in RW tabs. Shop ID and Job ID are the same value.

Filename exceptions: `CXE_Q1 2026` and `CX Orlando_Q1 2026` (no project part),
`HSB_Multi-Projects_Q1 2026` (several projects in one file), and `IntelliShop` / `Intellishop`
casing. The `Form` column holds a finer level (e.g. several forms inside one project).

## Principles
- One fact row per form with independent event dates. Received / Edited / QC Done are counted by
  their own dates, never by current status.
- Identity of a form = (client, project, job_id). Duplicates are flagged and excluded from
  counts, never deleted.
- Unmapped columns go to `forms.extra` (jsonb) and are listed in Data Health.
- Incremental sync keyed on Drive `modifiedTime`; vanished rows get `deleted_at`.
- Monthly snapshots are frozen for period comparisons.
- Credential tabs are excluded by `sheet_rule` before any cell is read.

## Tables
```
src_file, src_sheet                      -- discovery registry (Drive file / tab)
dim_client, client_alias                 -- "IntelliShop"/"Intellishop" -> one client
dim_project                              -- UK (client_id, name); for multi-project files derived from Form
dim_person, person_alias                 -- editors + QC members (a person can be both)
dim_error_category                       -- seeded from Master sheet
forms                                    -- fact table
rework                                   -- one row per RW-tab row
escalations                              -- Escalation tab rows
sync_log, sync_issue                     -- run history + per-row/file issues (Data Health)
column_map, status_map, sheet_rule       -- admin-editable mapping layer
snapshot_monthly                         -- frozen period metrics
```

`forms` (revised):
id, client_id, project_id, job_id, form_name, location, platform,
received_date (Input Date), shop_date, edit_date (Transaction Date), qc_date (QC Date),
editor_type (iSN Team | Freelancer), editor_id, qc_member_id,
input_status, edit_status (Ops Status), qc_status, hold_category, incomplete_status,
client_escalation (bool/text), error_category_raw, comments_to_shopper, qc_feedback,
source_sheet_id, source_row_no, row_hash, is_duplicate, dup_of_id, extra jsonb,
first_seen_at, last_seen_at, deleted_at.
Upsert key: (client_id, project_id, job_id).

`rework`: id, client_id, project_id, job_id, form_id (nullable), rw_seq (ordinal of this job's
RW rows by date), rw_date (Transaction Date), rw_editor_id, editor_type, rw_status, qc_member_id,
qc_date, qc_status, feedback, error_category, shop_date, source_sheet_id, source_row_no, row_hash.

`escalations`: id, client_id, project_id, job_id (nullable), form_id (nullable), raised_date,
editor_id, editor_type, qc_member_id, qc_date, client_feedback, root_cause, preventive_action,
corrective_action, remarks, action_status (default 'open'), error_category_id, source_sheet_id, row_hash.

## Mapping pipeline
1. Discover Year > `Qn_YYYY` > workbook > tabs; parse `<ClientCode>_<Project>_<Quarter Year>`
   with fallbacks (no project part, multi-project, client alias).
2. Classify tabs with `sheet_rule` (table above). Credential tabs are never fetched.
3. Locate the header row by alias scoring, normalise headers, resolve via `column_map`
   (precedence project > client > global). Positional fallback for blank `Input Date` /
   `QC Status` headers.
4. Row validity: must have a Job/Shop ID. Normalise dates (US month-first, 2- and 4-digit
   years), `status_map`, `person_alias`, `client_alias`. Unresolved values are kept raw and logged.

## Security note
`Login Details` tabs in these workbooks hold plaintext usernames and passwords for client
platforms and internal accounts. The ETL excludes them by rule, but the sheets are shared with
the service account, so recommend moving those credentials to a password manager and rotating them.

## Decisions confirmed by the business
- Form identity = (client, project, job_id); Shop ID and Job ID are the same value.
- Rework lives in the `RW` tab of each workbook (separate rows, several rounds per job).
- Received = Input Date (when the form arrived). Edited = Transaction Date. QC Done = QC Date,
  with analytics on *who* did how much QC and *when*. Ops Status is the current state under the
  QC rules. Shop Date is only the shopper's visit date.
- Only `Edited & Saved` counts as Edited (stored as `status_map.counts_as_edited`, so it can be
  changed in Admin without code). `Finalized` / `Client Finalized` count as Finalised.
- Projects where no row has a QC Member / QC Date are "QC not applicable" (excluded from QC %
  and QC pending). Admin can override per project (`dim_project.qc_applicable_override`).
- Naming hierarchy: file prefix (HSB, APC, CXE, CX Orlando, ...) -> the shop/brand name in the
  middle of the filename -> the `Form` column.

## Assumptions to confirm (made so work could continue)
1. **Edited counts.** Several workbooks (IntelliShop, RBG, Integritus, Confero samples) have no
   `Edited & Saved` rows at all, only `Finalized`. With the "Edited & Saved only" rule, Edited
   will be near zero for them while Finalised is high. Is that intended?
2. **Labels.** The business calls the file prefix a "project" and the middle part a "shop".
   The schema keeps `dim_client` (prefix) and `dim_project` (middle part); the UI labels are
   read from `app_setting` so they can say whatever the business wants. Which words should the
   dashboard show for level 1 and level 2?
3. **Files with no middle part** (`CXE`, `CX Orlando`) and **`HSB_Multi-Projects`**: level 2 is
   taken from the `Form` column (text before the first `:` if present, else the whole value).
4. **Duplicates.** One `forms` row per identity; later occurrences increment `dup_count` and are
   logged in `sync_issue` (type `duplicate`). Winner = row from the most recently modified file.
5. **RW rows** do not count as Edited for editor productivity, only as rework.
6. **`Error Category`** is pre-filled `QCD` on every operational row, so it is stored raw but not
   used for analytics. Error analysis uses the Escalation / RW tabs and `Master` categories.
7. **Auth:** single organisation, Admin / Manager / Viewer only.
