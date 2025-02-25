"""job priorities

Revision ID: fd79503179dd
Revises: 20e7d3ca289a
Create Date: 2025-02-25 15:39:24.833973

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fd79503179dd'
down_revision = '20e7d3ca289a'
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.add_column('job', sa.Column('priority', sa.Integer(), server_default='50', nullable=False))
        op.create_index('ix_state_run_at_taken_at_priority', 'job', ['state', 'run_at', 'taken_at', 'priority'], unique=False, postgresql_concurrently=True)
        op.drop_index('ix_state_run_at_taken_at', table_name='job', postgresql_concurrently=True)


def downgrade():
    with op.get_context().autocommit_block():
        op.drop_index('ix_state_run_at_taken_at_priority', table_name='job',  postgresql_concurrently=True)
        op.create_index('ix_state_run_at_taken_at', 'job', ['state', 'run_at', 'taken_at'], unique=False, postgresql_concurrently=True)
        op.drop_column('job', 'priority')
