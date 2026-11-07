"""merge partner user indices with sender blacklist

Revision ID: e5a9c2d4b8f1
Revises: c3d8e1f0a7b2, d4f7a1b9e620
Create Date: 2026-11-07 10:00:00.000000

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5a9c2d4b8f1'
down_revision = ('c3d8e1f0a7b2', 'd4f7a1b9e620')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
