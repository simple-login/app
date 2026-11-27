"""contact alias user and domain deleted alias email indices

Revision ID: c17f7f073e1d
Revises: d4f7a1b9e620
Create Date: 2026-11-10 10:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "c17f7f073e1d"
down_revision = "d4f7a1b9e620"
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_contact_alias_id_user_id",
            "contact",
            ["alias_id", "user_id"],
            unique=False,
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_domain_deleted_alias_email",
            "domain_deleted_alias",
            ["email"],
            unique=False,
            postgresql_concurrently=True,
        )


def downgrade():
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_domain_deleted_alias_email",
            table_name="domain_deleted_alias",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_contact_alias_id_user_id",
            table_name="contact",
            postgresql_concurrently=True,
        )
