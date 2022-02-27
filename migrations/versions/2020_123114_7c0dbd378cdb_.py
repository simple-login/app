"""empty message

Revision ID: 7c0dbd378cdb
Revises: f66ca777f409
Create Date: 2020-12-31 14:46:17.781348

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7c0dbd378cdb'
down_revision = 'f66ca777f409'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('users', 'default_random_alias_public_domain_id', new_column_name='default_alias_public_domain_id')



def downgrade():
    op.alter_column('users', 'default_alias_public_domain_id', new_column_name='default_random_alias_public_domain_id')

