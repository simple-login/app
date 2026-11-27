"""merge fido credential metadata with sender blacklist

Revision ID: 4f8a6a699d84
Revises: 4a9f8c2e1b3d, 9c2a7f3c1b21
Create Date: 2026-08-25 15:09:52.717844

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4f8a6a699d84'
down_revision = ('4a9f8c2e1b3d', '9c2a7f3c1b21')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
