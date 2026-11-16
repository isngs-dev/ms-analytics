"""keep every tab: raw rows of reference tabs, and read-everything sheet rules

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-16 09:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('src_sheet', sa.Column('header', JSONB(), nullable=True))
    op.create_table(
        'src_record',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('sheet_id', sa.Integer(), sa.ForeignKey('src_sheet.id', ondelete='CASCADE'), nullable=False),
        sa.Column('row_no', sa.Integer(), nullable=False),
        sa.Column('cells', JSONB(), nullable=False),
        sa.UniqueConstraint('sheet_id', 'row_no'),
    )
    op.create_index('ix_src_record_sheet_id', 'src_record', ['sheet_id'])
    # every sheet re-read cleans up the rows that left it, which looks them up by source sheet
    for table in ('forms', 'rework', 'escalations'):
        op.create_index(f'ix_{table}_source_sheet', table, ['source_sheet_id'])
    # Pivot / e-mail / update / 'Copy of' / Incomplete / client-query tabs used to be skipped unread. They are now
    # read: form-like ones add the Job IDs the main tabs lack, the rest are stored as raw rows. Credential tabs
    # (rule priority 10) stay unread, always.
    op.execute("""
        UPDATE sheet_rule SET kind = 'reference', read_cells = true
        WHERE priority IN (30, 40, 41, 42, 70, 80) AND kind IN ('ignored', 'client_query')
    """)


def downgrade() -> None:
    for table in ('forms', 'rework', 'escalations'):
        op.drop_index(f'ix_{table}_source_sheet', table_name=table)
    op.drop_index('ix_src_record_sheet_id', table_name='src_record')
    op.drop_table('src_record')
    op.drop_column('src_sheet', 'header')
