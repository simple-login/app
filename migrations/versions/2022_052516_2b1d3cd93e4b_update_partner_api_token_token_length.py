"""update partner_api_token token length

Revision ID: 2b1d3cd93e4b
Revises: 088f23324464
Create Date: 2022-05-25 16:43:33.017076

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2b1d3cd93e4b'
down_revision = '088f23324464'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('partner_api_token', 'token',
                    existing_type=sa.String(length=32),
                    type_=sa.String(length=50),
                    nullable=False)


def downgrade():
    op.alter_column('partner_api_token', 'token',
                    existing_type=sa.String(length=50),
                    type_=sa.String(length=32),
                    nullable=False)
