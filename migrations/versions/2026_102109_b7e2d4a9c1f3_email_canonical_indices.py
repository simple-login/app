"""email canonical indices

Revision ID: b7e2d4a9c1f3
Revises: 4a9f8c2e1b3d
Create Date: 2026-10-21 09:25:00.000000

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7e2d4a9c1f3'
down_revision = '4a9f8c2e1b3d'
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.create_index('ix_users_email_canonical', 'users', [sa.text("replace(split_part(split_part(lower(email), '@', 1), '+', 1), '.', '')"), sa.text("split_part(lower(email), '@', 2)")], unique=False, postgresql_concurrently=True)
        op.create_index('ix_mailbox_email_canonical', 'mailbox', [sa.text("replace(split_part(split_part(lower(email), '@', 1), '+', 1), '.', '')"), sa.text("split_part(lower(email), '@', 2)")], unique=False, postgresql_concurrently=True)


def downgrade():
    with op.get_context().autocommit_block():
        op.drop_index('ix_mailbox_email_canonical', table_name='mailbox', postgresql_concurrently=True)
        op.drop_index('ix_users_email_canonical', table_name='users', postgresql_concurrently=True)
