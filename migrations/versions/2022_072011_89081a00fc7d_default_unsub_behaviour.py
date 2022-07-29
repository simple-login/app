"""default_unsub_behaviour

Revision ID: 89081a00fc7d
Revises: b0101a66bb77
Create Date: 2022-07-20 11:32:32.424358

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '89081a00fc7d'
down_revision = 'b0101a66bb77'
branch_labels = None
depends_on = None


def upgrade():
    # See UnsubscribeBehaviourEnum for the meaning of the values (0 is disable alias)
    op.execute("ALTER TABLE users ALTER unsub_behaviour SET DEFAULT 0")


def downgrade():
    # See UnsubscribeBehaviourEnum for the meaning of the values (2 is preserve original)
    op.execute("ALTER TABLE users ALTER unsub_behaviour SET DEFAULT 2")
