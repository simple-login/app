"""empty message

Revision ID: 0809266d08ca
Revises: e9395fe234a4
Create Date: 2020-03-17 11:56:05.392474

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0809266d08ca"
down_revision = "e9395fe234a4"
branch_labels = None
depends_on = None


def upgrade():
    # alias_used_on table
    op.alter_column("alias_used_on", "gen_email_id", new_column_name="alias_id")
    op.drop_constraint("uq_alias_used", "alias_used_on", type_="unique")
    op.create_unique_constraint(
        "uq_alias_used", "alias_used_on", ["alias_id", "hostname"]
    )
    op.drop_constraint(
        "alias_used_on_gen_email_id_fkey", "alias_used_on", type_="foreignkey"
    )
    op.create_foreign_key(
        None, "alias_used_on", "alias", ["alias_id"], ["id"], ondelete="cascade"
    )

    # client_user table
    op.alter_column("client_user", "gen_email_id", new_column_name="alias_id")
    op.drop_constraint(
        "client_user_gen_email_id_fkey", "client_user", type_="foreignkey"
    )
    op.create_foreign_key(
        None, "client_user", "alias", ["alias_id"], ["id"], ondelete="cascade"
    )

    # contact table
    op.alter_column("contact", "gen_email_id", new_column_name="alias_id")
    op.create_unique_constraint("uq_contact", "contact", ["alias_id", "website_email"])
    op.drop_constraint("uq_forward_email", "contact", type_="unique")
    op.drop_constraint("forward_email_gen_email_id_fkey", "contact", type_="foreignkey")
    op.create_foreign_key(
        None, "contact", "alias", ["alias_id"], ["id"], ondelete="cascade"
    )


def downgrade():
    # One-way only
    # Too complex to downgrade
    raise Exception("Cannot downgrade")
