"""alias_audit_log_index_created_at

Revision ID: 32f25cbf12f6
Revises: 7d7b84779837
Create Date: 2024-10-16 16:45:36.827161

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '32f25cbf12f6'
down_revision = '7d7b84779837'
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.create_index('ix_alias_audit_log_created_at', 'alias_audit_log', ['created_at'], unique=False, postgresql_concurrently=True)


def downgrade():
    with op.get_context().autocommit_block():
        op.drop_index('ix_alias_audit_log_created_at', table_name='alias_audit_log', postgresql_concurrently=True)
