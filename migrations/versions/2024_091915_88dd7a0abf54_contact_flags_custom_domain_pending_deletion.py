"""contact.flags and custom_domain.pending_deletion

Revision ID: 88dd7a0abf54
Revises: 2441b7ff5da9
Create Date: 2024-09-19 15:41:20.910374

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '88dd7a0abf54'
down_revision = '2441b7ff5da9'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('contact', sa.Column('flags', sa.Integer(), server_default='0', nullable=False))
    op.add_column('custom_domain', sa.Column('pending_deletion', sa.Boolean(), server_default='0', nullable=False))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('custom_domain', 'pending_deletion')
    op.drop_column('contact', 'flags')
    # ### end Alembic commands ###
