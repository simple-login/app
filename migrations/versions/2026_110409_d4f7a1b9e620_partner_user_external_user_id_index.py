"""partner user external user id index

Revision ID: d4f7a1b9e620
Revises: c8a31f7d902e
Create Date: 2026-11-04 09:12:41.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "d4f7a1b9e620"
down_revision = "c8a31f7d902e"
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_partner_user_external_user_id",
            "partner_user",
            ["external_user_id"],
            unique=False,
            postgresql_concurrently=True,
        )


def downgrade():
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_partner_user_external_user_id",
            table_name="partner_user",
            postgresql_concurrently=True,
        )
