"""Add credential metadata columns to fido table

Revision ID: 4a9f8c2e1b3d
Revises: 3ee37864eb67
Create Date: 2026-03-19 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4a9f8c2e1b3d'
down_revision = '3ee37864eb67'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('fido', sa.Column('credential_type', sa.String(length=32), nullable=True))
    op.add_column('fido', sa.Column('authenticator_attachment', sa.String(length=32), nullable=True))
    op.add_column('fido', sa.Column('transports', sa.Text(), nullable=True))
    op.add_column('fido', sa.Column('aaguid', sa.String(length=36), nullable=True))


def downgrade():
    op.drop_column('fido', 'aaguid')
    op.drop_column('fido', 'transports')
    op.drop_column('fido', 'authenticator_attachment')
    op.drop_column('fido', 'credential_type')
