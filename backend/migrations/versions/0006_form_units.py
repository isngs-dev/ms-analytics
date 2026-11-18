"""forms.units: how many forms a row stands for (the '#images' cell for Global Data)

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-17 09:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('forms', sa.Column('units', sa.Integer(), nullable=False, server_default='1'))
    # rows already loaded: take the image count from the cell kept in `extra`
    op.execute(r"""
        UPDATE forms SET units = GREATEST(0, ROUND((forms.extra->>'#images')::numeric))::int
        FROM dim_project p
        WHERE p.id = forms.project_id AND lower(p.name) = 'global data'
          AND forms.extra->>'#images' ~ '^[0-9]+(\.[0-9]+)?$'
    """)


def downgrade() -> None:
    op.drop_column('forms', 'units')
