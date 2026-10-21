"""Increase the stored TOTP secret length to match PyOTP defaults.

Revision ID: 6af9b1832c47
Revises: b7e2d4a9c1f3
Create Date: 2026-10-21 10:08:19.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6af9b1832c47"
down_revision = "b7e2d4a9c1f3"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "users",
        "otp_secret",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=True,
    )


def downgrade():
    op.alter_column(
        "users",
        "otp_secret",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
        existing_nullable=True,
    )
