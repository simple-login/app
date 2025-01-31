"""index cleanup

Revision ID: d3ff8848c930
Revises: 085f77996ce3
Create Date: 2025-01-30 15:00:02.995813

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "d3ff8848c930"
down_revision = "085f77996ce3"
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.drop_index("ix_alias_hibp_alias_id", table_name="alias_hibp")
        op.drop_index("ix_alias_mailbox_alias_id", table_name="alias_mailbox")
        op.drop_index("ix_alias_used_on_alias_id", table_name="alias_used_on")
        op.drop_index("ix_api_key_code", table_name="api_key")
        op.drop_index(
            "ix_auto_create_rule_custom_domain_id", table_name="auto_create_rule"
        )
        op.drop_index("ix_contact_alias_id", table_name="contact")
        op.create_index(
            "ix_email_log_user_id_email_log_id",
            "email_log",
            ["user_id", "id"],
            unique=False,
        )
        op.drop_index("ix_job_state", table_name="job")
        op.create_index(
            "ix_mailbox_email_trgm_idx",
            "mailbox",
            ["email"],
            unique=False,
            postgresql_ops={"email": "gin_trgm_ops"},
            postgresql_using="gin",
        )
        op.drop_index("ix_partner_user_partner_id", table_name="partner_user")
        op.create_index(
            "ix_sent_alert_alert_type", "sent_alert", ["alert_type"], unique=False
        )
        op.create_index(
            "ix_sent_alert_to_email", "sent_alert", ["to_email"], unique=False
        )
        op.create_index(
            "idx_users_email_trgm",
            "users",
            ["email"],
            unique=False,
            postgresql_ops={"email": "gin_trgm_ops"},
            postgresql_using="gin",
        )
        op.drop_index("ix_users_activated", table_name="users")
        op.drop_index("ix_mailbox_user_id", table_name="users")


def downgrade():
    with op.get_context().autocommit_block():
        op.create_index("ix_users_activated", "users", ["activated"], unique=False)
        op.drop_index("idx_users_email_trgm", table_name="users")
        op.drop_index("ix_sent_alert_to_email", table_name="sent_alert")
        op.drop_index("ix_sent_alert_alert_type", table_name="sent_alert")
        op.create_index(
            "ix_partner_user_partner_id", "partner_user", ["partner_id"], unique=False
        )
        op.drop_index("ix_mailbox_email_trgm_idx", table_name="mailbox")
        op.create_index("ix_job_state", "job", ["state"], unique=False)
        op.drop_index("ix_email_log_user_id_email_log_id", table_name="email_log")
        op.create_index("ix_contact_alias_id", "contact", ["alias_id"], unique=False)
        op.create_index(
            "ix_auto_create_rule_custom_domain_id",
            "auto_create_rule",
            ["custom_domain_id"],
            unique=False,
        )
        op.create_index("ix_api_key_code", "api_key", ["code"], unique=False)
        op.create_index(
            "ix_alias_used_on_alias_id", "alias_used_on", ["alias_id"], unique=False
        )
        op.create_index(
            "ix_alias_mailbox_alias_id", "alias_mailbox", ["alias_id"], unique=False
        )
        op.create_index(
            "ix_alias_hibp_alias_id", "alias_hibp", ["alias_id"], unique=False
        )
        op.create_index("ix_mailbox_user_id", "users", ["user_id"], unique=False)
