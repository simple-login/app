"""Job missing index

Revision ID: 51a061fd6ef0
Revises: 07855f9f39b1
Create Date: 2025-05-05 11:06:43.058096

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '51a061fd6ef0'
down_revision = '07855f9f39b1'
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.create_index('ix_state_run_at_taken_at_priority_attempts', 'job', ['state', 'run_at', 'taken_at', 'priority', 'attempts'], unique=False, postgresql_concurrently=True)
        op.drop_index('ix_state_run_at_taken_at_priority', table_name='job', postgresql_concurrently=True)


def downgrade():
    with op.get_context().autocommit_block():
        op.create_index('ix_state_run_at_taken_at_priority', 'job', ['state', 'run_at', 'taken_at', 'priority'], unique=False, postgresql_concurrently=True)
        op.drop_index('ix_state_run_at_taken_at_priority_attempts', table_name='job', postgresql_concurrently=True)
