"""alias_trash

Revision ID: 07855f9f39b1
Revises: fd79503179dd
Create Date: 2025-03-10 15:06:14.889887

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '07855f9f39b1'
down_revision = 'fd79503179dd'
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.add_column('alias', sa.Column('delete_on', sqlalchemy_utils.types.arrow.ArrowType(), default=None, server_default=None, nullable=True))
        op.add_column('alias', sa.Column('delete_reason', sa.Integer(), default=None, server_default=None, nullable=True))
        op.create_index('ix_alias_delete_on', 'alias', ['delete_on'], unique=False, postgresql_concurrently=True)
        op.add_column('users', sa.Column('alias_delete_action', sa.Integer(), server_default='0', nullable=False))


def downgrade():
    with op.get_context().autocommit_block():
        op.drop_column('users', 'alias_delete_action')
        op.drop_index('ix_alias_delete_on', table_name='alias')
        op.drop_column('alias', 'delete_reason')
        op.drop_column('alias', 'delete_on')
