"""User sender blacklist (extend global sender blacklist)

Revision ID: 9c2a7f3c1b21
Revises: b7c1d6a4f2e1
Create Date: 2026-04-27

"""

from alembic import op
import sqlalchemy as sa


def _drop_unique_constraint_on_pattern_if_present():
    """Drop the UNIQUE(pattern) constraint safely.

    Important: On PostgreSQL, attempting to drop a non-existent constraint
    aborts the transaction. Catching the exception in Python is not enough
    because the transaction remains in a failed state.

    Therefore we *reflect* existing unique constraints first and only drop
    when we have an actual name.
    """

    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        uniques = insp.get_unique_constraints("global_sender_blacklist")
    except Exception:
        uniques = []

    for uc in uniques:
        cols = uc.get("column_names") or []
        if cols == ["pattern"]:
            name = uc.get("name")
            if name:
                op.drop_constraint(name, "global_sender_blacklist", type_="unique")
            break


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
    _drop_unique_constraint_on_pattern_if_present()


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
