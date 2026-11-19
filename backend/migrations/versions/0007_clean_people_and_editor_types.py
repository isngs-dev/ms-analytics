"""clean shifted-column garbage: dates / numbers as editor types and as people

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-19 12:00:00.000000
"""
from alembic import op


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None

GARBAGE = r"""(name !~ '[A-Za-z]{2}' OR lower(name) IN ('na','n/a','none','nil','tbd','yes','no','null','-','--'))"""


def upgrade() -> None:
    # Editor column: only 'iSN Team' / 'Freelancer' mean something
    for table in ('forms', 'rework', 'escalations'):
        op.execute(f"""
            UPDATE {table} SET editor_type = CASE WHEN editor_type ILIKE '%isn%' THEN 'iSN Team'
                                                  WHEN editor_type ILIKE '%freelanc%' THEN 'Freelancer' END
            WHERE editor_type IS NOT NULL AND editor_type NOT IN ('iSN Team', 'Freelancer')
        """)
    # people that are really dates / numbers / placeholders: detach them, then remove them
    op.execute(f"CREATE TEMP TABLE junk_person AS SELECT id FROM dim_person WHERE {GARBAGE}")
    for table, col in (('forms', 'editor_id'), ('forms', 'qc_member_id'), ('rework', 'rw_editor_id'),
                       ('rework', 'qc_member_id'), ('escalations', 'editor_id'), ('escalations', 'qc_member_id')):
        op.execute(f"UPDATE {table} SET {col} = NULL WHERE {col} IN (SELECT id FROM junk_person)")
    op.execute("DELETE FROM person_alias WHERE person_id IN (SELECT id FROM junk_person)")
    op.execute("DELETE FROM dim_person WHERE id IN (SELECT id FROM junk_person)")
    op.execute("DROP TABLE junk_person")


def downgrade() -> None:
    pass  # the removed values were junk; nothing to restore
