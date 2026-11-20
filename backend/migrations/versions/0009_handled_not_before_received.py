"""a form handled before it was received counts as handled on its Input Date

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-20 15:00:00.000000

Data fix only (no schema change). Some sheets carry a Transaction Date earlier than the Input Date (a typo or a
back-dated entry), which made Finalised and Received disagree. The loader now applies the same rule to new rows.
Not reversible: a forced re-sync after removing the rule from etl/loader.py restores the sheet values.
"""
from alembic import op

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    n = op.get_bind().exec_driver_sql(
        "UPDATE forms SET edit_date = received_date WHERE edit_date < received_date").rowcount
    print(f"0009: {n} form(s) had a Transaction Date before the Input Date; moved to the Input Date")


def downgrade() -> None:
    pass
