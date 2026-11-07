"""partner user email trigram index

Revision ID: c8a31f7d902e
Revises: b7e2d4a9c1f3
Create Date: 2026-10-22 15:35:30.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "c8a31f7d902e"
down_revision = "b7e2d4a9c1f3"
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_partner_user_partner_email_trgm",
            "partner_user",
            ["partner_email"],
            unique=False,
            postgresql_ops={"partner_email": "gin_trgm_ops"},
            postgresql_using="gin",
            postgresql_concurrently=True,
        )


def downgrade():
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_partner_user_partner_email_trgm",
            table_name="partner_user",
            postgresql_concurrently=True,
        )
