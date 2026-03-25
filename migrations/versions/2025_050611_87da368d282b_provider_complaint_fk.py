"""Provider Complaint FK

Revision ID: 87da368d282b
Revises: 51a061fd6ef0
Create Date: 2025-05-06 11:43:22.432227

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '87da368d282b'
down_revision = '51a061fd6ef0'
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.drop_constraint('provider_complaint_user_id_fkey', 'provider_complaint', type_='foreignkey')
        op.create_foreign_key(None, 'provider_complaint', 'users', ['user_id'], ['id'], ondelete='cascade')


def downgrade():
    with op.get_context().autocommit_block():
        op.drop_constraint(None, 'provider_complaint', type_='foreignkey')
        op.create_foreign_key('provider_complaint_user_id_fkey', 'provider_complaint', 'users', ['user_id'], ['id'])
