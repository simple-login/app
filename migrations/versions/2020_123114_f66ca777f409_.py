"""empty message

Revision ID: f66ca777f409
Revises: 1919f1859215
Create Date: 2020-12-31 14:01:54.065360

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f66ca777f409'
down_revision = '1919f1859215'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('users', 'default_random_alias_domain_id', new_column_name='default_alias_custom_domain_id')



def downgrade():
    op.alter_column('users', 'default_alias_custom_domain_id', new_column_name='default_random_alias_domain_id')
