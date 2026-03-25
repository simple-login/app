"""deleted alias id

Revision ID: 3ffdea52697d
Revises: 9e80159405af
Create Date: 2025-09-04 09:57:23.255112

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3ffdea52697d'
down_revision = '9e80159405af'
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.add_column('deleted_alias', sa.Column('alias_id', sa.Integer(), nullable=True))
        op.create_index(op.f('ix_deleted_alias_alias_id'), 'deleted_alias', ['alias_id'], unique=False, postgresql_concurrently=True)
        op.add_column('domain_deleted_alias', sa.Column('alias_id', sa.Integer(), nullable=True))
        op.create_index('ix_domain_deleted_alias_alias_id', 'domain_deleted_alias', ['alias_id'], unique=False, postgresql_concurrently=True)


def downgrade():
    with op.get_context().autocommit_block():
        op.drop_index('ix_domain_deleted_alias_alias_id', table_name='domain_deleted_alias', postgresql_concurrently=True)
        op.drop_column('domain_deleted_alias', 'alias_id')
        op.drop_index(op.f('ix_deleted_alias_alias_id'), table_name='deleted_alias', postgresql_concurrently=True)
        op.drop_column('deleted_alias', 'alias_id')

