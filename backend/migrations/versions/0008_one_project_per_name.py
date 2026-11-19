"""name rows without a Form clearly, and merge projects that differ only in spelling

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-19 16:00:00.000000

Data fix only (no schema change): see app.etl.project_names. Not reversible (the old spellings are not kept), which is
harmless: every form keeps its own text in forms.form_name and the loader now files new rows the same way.
"""
from alembic import op
from sqlalchemy.orm import Session

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.etl.project_names import fix_project_names

    session = Session(bind=op.get_bind())
    out = fix_project_names(session)
    session.flush()
    print(f"0008: {out['renamed']} project(s) renamed, {out['merged']} spelling variant(s) merged")


def downgrade() -> None:
    pass
