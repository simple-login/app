"""Add global sender blacklist

Revision ID: b7c1d6a4f2e1
Revises: 4a9f8c2e1b3d
Create Date: 2026-04-26

"""

import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b7c1d6a4f2e1"
down_revision = "4a9f8c2e1b3d"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "global_sender_blacklist",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at", sqlalchemy_utils.types.arrow.ArrowType(), nullable=False
        ),
        sa.Column("updated_at", sqlalchemy_utils.types.arrow.ArrowType(), nullable=True),
        sa.Column("pattern", sa.String(length=512), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pattern"),
    )


def downgrade():
    op.drop_table("global_sender_blacklist")
