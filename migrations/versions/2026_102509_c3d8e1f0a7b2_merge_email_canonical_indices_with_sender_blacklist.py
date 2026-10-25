"""merge email canonical indices with sender blacklist

Revision ID: c3d8e1f0a7b2
Revises: 4f8a6a699d84, b7e2d4a9c1f3
Create Date: 2026-10-25 09:40:00.000000

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d8e1f0a7b2'
down_revision = ('4f8a6a699d84', 'b7e2d4a9c1f3')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
