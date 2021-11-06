"""empty message

Revision ID: 1076b5795b08
Revises: dd278f96ca83
Create Date: 2021-11-06 12:36:11.352157

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1076b5795b08'
down_revision = 'dd278f96ca83'
branch_labels = None
depends_on = None


def upgrade():
    # As alembic cannot detect changes in column type, do it manually
    op.execute('ALTER TABLE fido ALTER COLUMN sign_count TYPE BIGINT;')


def downgrade():
    op.execute('ALTER TABLE fido ALTER COLUMN sign_count TYPE int;')
