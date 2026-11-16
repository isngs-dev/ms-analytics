"""index escalations by job so quality (feedback per edited report) joins stay fast

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-13 12:30:00.000000
"""
from alembic import op


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index('ix_esc_job', 'escalations', ['client_id', 'project_id', 'job_id'])


def downgrade() -> None:
    op.drop_index('ix_esc_job', table_name='escalations')
