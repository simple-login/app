"""Add display name to auto create rule

Revision ID: f3d65fe0b5b4
Revises: 3ffdea52697d
Create Date: 2025-11-13 15:42:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f3d65fe0b5b4'
down_revision = '3ffdea52697d'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'auto_create_rule',
        sa.Column(
            'display_name',
            sa.String(length=128),
            nullable=True,
            server_default=None,
        ),
    )


def downgrade():
    op.drop_column('auto_create_rule', 'display_name')
