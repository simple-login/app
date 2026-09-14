"""Add independent DKIM/DMARC debounce columns to custom_domain

Revision ID: b7c1a9d3e2f4
Revises: 4a9f8c2e1b3d
Create Date: 2026-09-04 12:00:00.000000

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b7c1a9d3e2f4"
down_revision = "4a9f8c2e1b3d"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "custom_domain",
        sa.Column(
            "dkim_nb_failed_checks", sa.Integer(), server_default="0", nullable=False
        ),
    )
    op.add_column(
        "custom_domain",
        sa.Column(
            "dkim_nb_failed_checks_updated_at",
            sqlalchemy_utils.types.arrow.ArrowType(),
            nullable=True,
        ),
    )
    op.add_column(
        "custom_domain",
        sa.Column(
            "dmarc_nb_failed_checks", sa.Integer(), server_default="0", nullable=False
        ),
    )
    op.add_column(
        "custom_domain",
        sa.Column(
            "dmarc_nb_failed_checks_updated_at",
            sqlalchemy_utils.types.arrow.ArrowType(),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column("custom_domain", "dmarc_nb_failed_checks_updated_at")
    op.drop_column("custom_domain", "dmarc_nb_failed_checks")
    op.drop_column("custom_domain", "dkim_nb_failed_checks_updated_at")
    op.drop_column("custom_domain", "dkim_nb_failed_checks")
