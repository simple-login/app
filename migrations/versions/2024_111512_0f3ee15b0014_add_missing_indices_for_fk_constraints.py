"""add missing indices for fk constraints

Revision ID: 0f3ee15b0014
Revises: 12274da2299f
Create Date: 2024-11-15 12:29:10.739938

"""
import sqlalchemy_utils
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0f3ee15b0014'
down_revision = '12274da2299f'
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.create_index('ix_activation_code_user_id', 'activation_code', ['user_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_alias_original_owner_id', 'alias', ['original_owner_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_alias_used_on_user_id', 'alias_used_on', ['user_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_api_to_cookie_token_api_key_id', 'api_cookie_token', ['api_key_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_api_to_cookie_token_user_id', 'api_cookie_token', ['user_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_api_key_code', 'api_key', ['code'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_api_key_user_id', 'api_key', ['user_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_authorization_code_client_id', 'authorization_code', ['client_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_authorization_code_user_id', 'authorization_code', ['user_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_authorized_address_user_id', 'authorized_address', ['user_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_auto_create_rule_custom_domain_id', 'auto_create_rule', ['custom_domain_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_batch_import_file_id', 'batch_import', ['file_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_batch_import_user_id', 'batch_import', ['user_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_client_icon_id', 'client', ['icon_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_client_referral_id', 'client', ['referral_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_client_user_id', 'client', ['user_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_coupon_used_by_user_id', 'coupon', ['used_by_user_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_directory_user_id', 'directory', ['user_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_domain_deleted_alias_user_id', 'domain_deleted_alias', ['user_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_email_log_refused_email_id', 'email_log', ['refused_email_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_fido_user_id', 'fido', ['user_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_file_user_id', 'file', ['user_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_hibp_notified_alias_user_id', 'hibp_notified_alias', ['user_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_mfa_browser_user_id', 'mfa_browser', ['user_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_newsletter_user_user_id', 'newsletter_user', ['user_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_oauth_token_client_id', 'oauth_token', ['client_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_oauth_token_user_id', 'oauth_token', ['user_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_payout_user_id', 'payout', ['user_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_phone_reservation_user_id', 'phone_reservation', ['user_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_provider_complaint_refused_email_id', 'provider_complaint', ['refused_email_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_provider_complaint_user_id', 'provider_complaint', ['user_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_redirect_uri_client_id', 'redirect_uri', ['client_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_referral_user_id', 'referral', ['user_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_refused_email_user_id', 'refused_email', ['user_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_reset_password_code_user_id', 'reset_password_code', ['user_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_sent_alert_user_id', 'sent_alert', ['user_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_users_default_alias_custom_domain_id', 'users', ['default_alias_custom_domain_id'], unique=False, postgresql_concurrently=True)
        op.create_index('ix_users_profile_picture_id', 'users', ['profile_picture_id'], unique=False, postgresql_concurrently=True)



def downgrade():
    with op.get_context().autocommit_block():
        op.drop_index('ix_users_profile_picture_id', table_name='users')
        op.drop_index('ix_users_default_alias_custom_domain_id', table_name='users')
        op.drop_index('ix_sent_alert_user_id', table_name='sent_alert')
        op.drop_index('ix_reset_password_code_user_id', table_name='reset_password_code')
        op.drop_index('ix_refused_email_user_id', table_name='refused_email')
        op.drop_index('ix_referral_user_id', table_name='referral')
        op.drop_index('ix_redirect_uri_client_id', table_name='redirect_uri')
        op.drop_index('ix_provider_complaint_user_id', table_name='provider_complaint')
        op.drop_index('ix_provider_complaint_refused_email_id', table_name='provider_complaint')
        op.drop_index('ix_phone_reservation_user_id', table_name='phone_reservation')
        op.drop_index('ix_payout_user_id', table_name='payout')
        op.drop_index('ix_oauth_token_user_id', table_name='oauth_token')
        op.drop_index('ix_oauth_token_client_id', table_name='oauth_token')
        op.drop_index('ix_newsletter_user_user_id', table_name='newsletter_user')
        op.drop_index('ix_mfa_browser_user_id', table_name='mfa_browser')
        op.drop_index('ix_hibp_notified_alias_user_id', table_name='hibp_notified_alias')
        op.drop_index('ix_file_user_id', table_name='file')
        op.drop_index('ix_fido_user_id', table_name='fido')
        op.drop_index('ix_email_log_refused_email_id', table_name='email_log')
        op.drop_index('ix_domain_deleted_alias_user_id', table_name='domain_deleted_alias')
        op.drop_index('ix_directory_user_id', table_name='directory')
        op.drop_index('ix_coupon_used_by_user_id', table_name='coupon')
        op.drop_index('ix_client_user_id', table_name='client')
        op.drop_index('ix_client_referral_id', table_name='client')
        op.drop_index('ix_client_icon_id', table_name='client')
        op.drop_index('ix_batch_import_user_id', table_name='batch_import')
        op.drop_index('ix_batch_import_file_id', table_name='batch_import')
        op.drop_index('ix_auto_create_rule_custom_domain_id', table_name='auto_create_rule')
        op.drop_index('ix_authorized_address_user_id', table_name='authorized_address')
        op.drop_index('ix_authorization_code_user_id', table_name='authorization_code')
        op.drop_index('ix_authorization_code_client_id', table_name='authorization_code')
        op.drop_index('ix_api_key_user_id', table_name='api_key')
        op.drop_index('ix_api_key_code', table_name='api_key')
        op.drop_index('ix_api_to_cookie_token_user_id', table_name='api_cookie_token')
        op.drop_index('ix_api_to_cookie_token_api_key_id', table_name='api_cookie_token')
        op.drop_index('ix_alias_used_on_user_id', table_name='alias_used_on')
        op.drop_index('ix_alias_original_owner_id', table_name='alias')
        op.drop_index('ix_activation_code_user_id', table_name='activation_code')
