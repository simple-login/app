"""Create admin audit log

Revision ID: b500363567e3
Revises: 9282e982bc05
Create Date: 2022-03-10 15:26:54.538717

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b500363567e3"
down_revision = "4729b7096d12"
branch_labels = None
depends_on = None


def upgrade():
    admin_table = op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sqlalchemy_utils.types.arrow.ArrowType(), nullable=False),
        sa.Column("admin_user_id", sa.Integer, nullable=False),
        sa.Column("action", sa.Integer, nullable=False),
        sa.Column("model", sa.String(length=256), nullable=False),
        sa.Column("model_id", sa.Integer, nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Index("admin_audit_log_admin_user_id_idx", 'admin_user_id'),
        sa.ForeignKeyConstraint(['admin_user_id'], ['users.id'], ondelete='cascade'),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("admin_audit_log")
