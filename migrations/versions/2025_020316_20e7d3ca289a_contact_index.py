"""contact index

Revision ID: 20e7d3ca289a
Revises: 97edba8794f8
Create Date: 2025-02-03 16:52:06.775032

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '20e7d3ca289a'
down_revision = '97edba8794f8'
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.create_index('ix_contact_user_id_id', 'contact', ['user_id', 'id'], unique=False)
        op.drop_index('ix_contact_user_id', table_name='contact')


def downgrade():
    with op.get_context().autocommit_block():
        op.create_index('ix_contact_user_id', 'contact', ['user_id'], unique=False)
        op.drop_index('ix_contact_user_id_id', table_name='contact')
