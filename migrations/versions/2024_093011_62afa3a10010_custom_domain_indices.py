"""custom domain indices

Revision ID: 62afa3a10010
Revises: 88dd7a0abf54
Create Date: 2024-09-30 11:40:04.127791

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '62afa3a10010'
down_revision = '88dd7a0abf54'
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.create_index('ix_custom_domain_pending_deletion', 'custom_domain', ['pending_deletion'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_custom_domain_user_id', 'custom_domain', ['user_id'], unique=False, postgresql_concurrently=True)


def downgrade():
    with op.get_context().autocommit_block():
        op.drop_index('ix_custom_domain_user_id', table_name='custom_domain', postgresql_concurrently=True)
        op.drop_index('ix_custom_domain_pending_deletion', table_name='custom_domain', postgresql_concurrently=True)
