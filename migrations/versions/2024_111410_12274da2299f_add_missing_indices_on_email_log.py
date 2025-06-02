"""add missing indices on email log

Revision ID: 12274da2299f
Revises: 842ac670096e
Create Date: 2024-11-14 10:27:20.371191

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '12274da2299f'
down_revision = '842ac670096e'
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.create_index('ix_email_log_bounced_mailbox_id', 'email_log', ['bounced_mailbox_id'], unique=False)
        op.create_index('ix_email_log_mailbox_id', 'email_log', ['mailbox_id'], unique=False)


def downgrade():
    with op.get_context().autocommit_block():
        op.drop_index('ix_email_log_mailbox_id', table_name='email_log')
        op.drop_index('ix_email_log_bounced_mailbox_id', table_name='email_log')
