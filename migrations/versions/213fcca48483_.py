"""empty message

Revision ID: 213fcca48483
Revises: 0256244cd7c8
Create Date: 2019-06-30 11:11:51.823062

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '213fcca48483'
down_revision = '0256244cd7c8'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('users', 'trial_expiration', new_column_name='plan_expiration')


def downgrade():
    op.alter_column('users', 'plan_expiration', new_column_name='trial_expiration')
