"""empty message

Revision ID: 14167121af69
Revises: 7744c5c16159
Create Date: 2020-03-17 11:00:00.400334

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "14167121af69"
down_revision = "7744c5c16159"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("forward_email_log", "forward_id", new_column_name="contact_id")
    op.drop_constraint(
        "forward_email_log_forward_id_fkey", "forward_email_log", type_="foreignkey"
    )
    op.create_foreign_key(
        None, "forward_email_log", "contact", ["contact_id"], ["id"], ondelete="cascade"
    )


def downgrade():
    op.alter_column("forward_email_log", "contact_id", new_column_name="forward_id")
