"""Client escalations written in the operational tabs.

Besides the dedicated 'Escalations' tabs, most workbooks note a client escalation straight on the form row (the
'Client Escalation' column, usually with Error Category and Company's Name beside it). Those rows are escalations too,
so every form with a non-blank Client Escalation becomes one row of the `escalations` table, which is what the
Escalations page, its filters, the drill-downs and the Overall quality figures all read.

  * a form already covered by a row of an Escalations tab (same client and Job ID) is skipped, never counted twice
  * the date is the form's Input Date (falling back to its handled / shop date), the people come from the form
  * corrective / preventive action, owner, status and root cause entered in the app are never overwritten
  * when the cell is cleared, the form is deleted or an Escalations tab starts to cover it, the derived row is removed

Runs at the end of every sync (also when no workbook changed), as plain SQL: a few milliseconds for ~500 rows.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

ORIGIN = "form_column"

_CANDIDATES = """
    SELECT f.id AS form_id, f.client_id, f.project_id, f.job_id,
           COALESCE(f.received_date, f.edit_date, f.shop_date) AS raised_date,
           f.editor_type, f.editor_id, f.qc_member_id, f.qc_date,
           btrim(f.client_escalation) AS feedback, c.id AS error_category_id,
           f.source_sheet_id, f.source_row_no
    FROM forms f
    LEFT JOIN dim_error_category c ON lower(btrim(c.name)) = lower(btrim(f.error_category_raw))
    WHERE f.deleted_at IS NULL AND btrim(COALESCE(f.client_escalation, '')) <> ''
      AND NOT EXISTS (SELECT 1 FROM escalations e
                      WHERE e.deleted_at IS NULL AND e.client_id = f.client_id AND e.job_id = f.job_id
                        AND COALESCE(e.extra ->> 'origin', '') <> :origin)
"""

_UPSERT = f"""
    INSERT INTO escalations (client_id, project_id, job_id, form_id, raised_date, editor_type, editor_id,
                             qc_member_id, qc_date, client_feedback, error_category_id, action_status,
                             source_sheet_id, source_row_no, row_hash, extra)
    SELECT client_id, project_id, job_id, form_id, raised_date, editor_type, editor_id, qc_member_id, qc_date,
           feedback, error_category_id, 'open', source_sheet_id, source_row_no,
           md5('form-escalation:' || form_id), jsonb_build_object('origin', CAST(:origin AS text))
    FROM ({_CANDIDATES}) cand
    ON CONFLICT (row_hash) DO UPDATE SET
        client_id = EXCLUDED.client_id, project_id = EXCLUDED.project_id, job_id = EXCLUDED.job_id,
        form_id = EXCLUDED.form_id, raised_date = EXCLUDED.raised_date, editor_type = EXCLUDED.editor_type,
        editor_id = EXCLUDED.editor_id, qc_member_id = EXCLUDED.qc_member_id, qc_date = EXCLUDED.qc_date,
        client_feedback = EXCLUDED.client_feedback,
        error_category_id = COALESCE(escalations.error_category_id, EXCLUDED.error_category_id),
        source_sheet_id = EXCLUDED.source_sheet_id, source_row_no = EXCLUDED.source_row_no, deleted_at = NULL
    WHERE escalations.deleted_at IS NOT NULL
       OR (escalations.client_id, escalations.project_id, escalations.job_id, escalations.raised_date,
           escalations.editor_id, escalations.qc_member_id, escalations.qc_date, escalations.client_feedback,
           escalations.editor_type, escalations.source_sheet_id, escalations.source_row_no)
          IS DISTINCT FROM
          (EXCLUDED.client_id, EXCLUDED.project_id, EXCLUDED.job_id, EXCLUDED.raised_date, EXCLUDED.editor_id,
           EXCLUDED.qc_member_id, EXCLUDED.qc_date, EXCLUDED.client_feedback, EXCLUDED.editor_type,
           EXCLUDED.source_sheet_id, EXCLUDED.source_row_no)
"""

_RETIRE = f"""
    UPDATE escalations SET deleted_at = now()
    WHERE deleted_at IS NULL AND extra ->> 'origin' = :origin
      AND (form_id IS NULL OR form_id NOT IN (SELECT form_id FROM ({_CANDIDATES}) cand))
"""


def sync_form_escalations(db: Session) -> dict[str, int]:
    """Bring the derived escalation rows in line with the forms. Returns how many rows were added / changed / removed."""
    params = {"origin": ORIGIN}
    changed = db.execute(text(_UPSERT), params).rowcount or 0
    removed = db.execute(text(_RETIRE), params).rowcount or 0
    db.commit()
    return {"written": changed, "removed": removed}
