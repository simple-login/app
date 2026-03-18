"""User sender blacklist (extend global sender blacklist)

Revision ID: 9c2a7f3c1b21
Revises: b7c1d6a4f2e1
Create Date: 2026-03-18

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9c2a7f3c1b21"
down_revision = "b7c1d6a4f2e1"
branch_labels = None
depends_on = None


def upgrade():
    # 1) Add user_id nullable so existing global entries stay valid.
    with op.batch_alter_table("global_sender_blacklist") as batch:
        batch.add_column(
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="cascade"),
                nullable=True,
            )
        )
        batch.create_index("ix_global_sender_blacklist_user_id", ["user_id"])

    # 2) Drop unique constraint on pattern so users can use the same pattern independently.
    #    Constraint name is backend-dependent; try a few common names.
    for name in (
        "global_sender_blacklist_pattern_key",  # PostgreSQL default
        "uq_global_sender_blacklist_pattern",  # potential naming convention
        "uq_global_sender_blacklist_pattern",  # (duplicate on purpose; harmless)
    ):
        try:
            op.drop_constraint(name, "global_sender_blacklist", type_="unique")
        except Exception:
            pass


def downgrade():
    # Re-create unique constraint on pattern (best-effort).
    try:
        op.create_unique_constraint(
            "global_sender_blacklist_pattern_key",
            "global_sender_blacklist",
            ["pattern"],
        )
    except Exception:
        pass

    with op.batch_alter_table("global_sender_blacklist") as batch:
        try:
            batch.drop_index("ix_global_sender_blacklist_user_id")
        except Exception:
            pass
        batch.drop_column("user_id")
