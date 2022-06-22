"""Add sudo expiration for ApiKeys

Revision ID: 4983e9c6fe9c
Revises: a7bcb872c12a
Create Date: 2022-06-22 17:51:19.547128

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4983e9c6fe9c'
down_revision = 'a7bcb872c12a'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('api_key', sa.Column('sudo_mode_at', sqlalchemy_utils.types.arrow.ArrowType(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('api_key', 'sudo_mode_at')
    # ### end Alembic commands ###
