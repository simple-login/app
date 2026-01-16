"""Add flags field to mailbox

Revision ID: 3ee37864eb67
Revises: f3d65fe0b5b4
Create Date: 2026-01-16 09:35:35.278049

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3ee37864eb67'
down_revision = 'f3d65fe0b5b4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('mailbox', sa.Column('flags', sa.BigInteger(), server_default='0', nullable=False))


def downgrade():
    op.drop_column('mailbox', 'flags')
