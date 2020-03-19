"""empty message

Revision ID: 7744c5c16159
Revises: 9081f1a90939
Create Date: 2020-03-17 09:52:10.662573

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "7744c5c16159"
down_revision = "91b69dfad2f1"
branch_labels = None
depends_on = None


def upgrade():
    op.rename_table("forward_email", "contact")


def downgrade():
    op.rename_table("contact", "forward_email")
