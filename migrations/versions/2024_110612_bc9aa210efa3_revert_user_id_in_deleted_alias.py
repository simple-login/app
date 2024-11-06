"""Revert user id on deleted alias

Revision ID: bc9aa210efa3
Revises: 4882cc49dde9
Create Date: 2024-11-06 12:44:44.129691

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bc9aa210efa3'
down_revision = '4882cc49dde9'
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.drop_index('ix_deleted_alias_user_id_created_at', table_name='deleted_alias')
    op.drop_column('deleted_alias', 'user_id')


def downgrade():
    op.add_column('deleted_alias', sa.Column('user_id', sa.Integer(), server_default=None, nullable=True))
    with op.get_context().autocommit_block():
        op.create_index('ix_deleted_alias_user_id_created_at', 'deleted_alias', ['user_id', 'created_at'], unique=False, postgresql_concurrently=True)
