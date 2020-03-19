"""empty message

Revision ID: 6e061eb84167
Revises: 14167121af69
Create Date: 2020-03-17 11:08:02.004125

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "6e061eb84167"
down_revision = "14167121af69"
branch_labels = None
depends_on = None


def upgrade():
    op.rename_table("forward_email_log", "email_log")


def downgrade():
    op.rename_table("email_log", "forward_email_log")
