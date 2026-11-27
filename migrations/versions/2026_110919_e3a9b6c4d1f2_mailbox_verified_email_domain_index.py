"""mailbox verified email domain index

Revision ID: e3a9b6c4d1f2
Revises: d4f7a1b9e620
Create Date: 2026-11-09 19:45:00.000000

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e3a9b6c4d1f2'
down_revision = 'd4f7a1b9e620'
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.create_index('ix_mailbox_verified_email_domain', 'mailbox', [sa.text("split_part(lower(email), '@', 2)")], unique=False, postgresql_where=sa.text('verified'), postgresql_concurrently=True)


def downgrade():
    with op.get_context().autocommit_block():
        op.drop_index('ix_mailbox_verified_email_domain', table_name='mailbox', postgresql_concurrently=True)
