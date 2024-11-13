"""Preserve user id on alias delete

Revision ID: 4882cc49dde9
Revises: 32f25cbf12f6
Create Date: 2024-11-06 10:10:40.235991

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4882cc49dde9'
down_revision = '32f25cbf12f6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('deleted_alias', sa.Column('user_id', sa.Integer(), server_default=None, nullable=True))
    with op.get_context().autocommit_block():
        op.create_index('ix_deleted_alias_user_id_created_at', 'deleted_alias', ['user_id', 'created_at'], unique=False, postgresql_concurrently=True)


def downgrade():
    with op.get_context().autocommit_block():
        op.drop_index('ix_deleted_alias_user_id_created_at', table_name='deleted_alias')
    op.drop_column('deleted_alias', 'user_id')
