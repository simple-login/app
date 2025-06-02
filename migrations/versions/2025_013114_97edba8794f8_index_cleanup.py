"""index cleanup

Revision ID: 97edba8794f8
Revises: d3ff8848c930
Create Date: 2025-01-31 14:42:22.590597

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '97edba8794f8'
down_revision = 'd3ff8848c930'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index('ix_email_log_user_id', table_name='email_log')


def downgrade():
    op.create_index('ix_email_log_user_id', 'email_log', ['user_id'], unique=False)
