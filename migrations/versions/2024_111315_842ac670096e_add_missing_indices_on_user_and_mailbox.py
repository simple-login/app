"""add missing indices on user and mailbox

Revision ID: 842ac670096e
Revises: bc9aa210efa3
Create Date: 2024-11-13 15:55:28.798506

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '842ac670096e'
down_revision = 'bc9aa210efa3'
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.create_index('ix_mailbox_pgp_finger_print', 'mailbox', ['pgp_finger_print'], unique=False)
        op.create_index('ix_users_default_mailbox_id', 'users', ['default_mailbox_id'], unique=False)
    # ### end Alembic commands ###


def downgrade():
    with op.get_context().autocommit_block():
        op.drop_index('ix_users_default_mailbox_id', table_name='users')
        op.drop_index('ix_mailbox_pgp_finger_print', table_name='mailbox')
