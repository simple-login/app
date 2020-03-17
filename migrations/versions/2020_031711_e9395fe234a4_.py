"""empty message

Revision ID: e9395fe234a4
Revises: 6e061eb84167
Create Date: 2020-03-17 11:37:33.157695

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "e9395fe234a4"
down_revision = "6e061eb84167"
branch_labels = None
depends_on = None


def upgrade():
    op.rename_table("gen_email", "alias")


def downgrade():
    op.rename_table("alias", "gen_email")
