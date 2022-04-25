"""Store transactional complaints for admins to verify

Revision ID: 45588d9bb475
Revises: b500363567e3
Create Date: 2022-04-19 16:17:42.798792

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '45588d9bb475'
down_revision = 'b500363567e3'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "provider_complaint",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sqlalchemy_utils.types.arrow.ArrowType(), nullable=False),
        sa.Column("updated_at", sqlalchemy_utils.types.arrow.ArrowType(), nullable=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("state", sa.Integer, nullable=False),
        sa.Column("phase", sa.Integer, nullable=False),
        sa.Column("refused_email_id", sa.Integer, nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='cascade'),
        sa.ForeignKeyConstraint(['refused_email_id'], ['refused_email.id'], ondelete='cascade'),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("provider_complaint")
