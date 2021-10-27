"""Increase message_id length manually

Revision ID: 0b9150eb309d
Revises: bbedc353f90c
Create Date: 2021-10-27 15:58:22.275769

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0b9150eb309d'
down_revision = 'bbedc353f90c'
branch_labels = None
depends_on = None


def upgrade():
    # As alembic cannot detect changes in column length, do it manually
    op.execute('ALTER TABLE email_log ALTER COLUMN message_id TYPE varchar(1024);')
    op.execute('ALTER TABLE message_id_matching ALTER COLUMN original_message_id TYPE varchar(1024);')


def downgrade():
    # As alembic cannot detect changes in column length, do it manually
    op.execute('ALTER TABLE email_log ALTER COLUMN message_id TYPE varchar(512);')
    op.execute('ALTER TABLE message_id_matching ALTER COLUMN original_message_id TYPE varchar(512);')
