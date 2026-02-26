"""Tests for admin email search functionality."""

import arrow
from flask import url_for

from app.db import Session
from app.models import (
    User,
    Alias,
    Mailbox,
    PartnerUser,
    ManualSubscription,
    UserAuditLog,
    AbuserAuditLog,
    Fido,
    AdminAuditLog,
    AuditLogActionEnum,
)
from app.proton.proton_partner import get_proton_partner
from tests.utils import create_new_user, random_token


def create_admin_user(email: str = None) -> User:
    """Create an admin user for testing."""
    if not email:
        email = f"admin_{random_token(10)}@mailbox.lan"
    user = User.create(
        email=email,
        password="password",
        name="Admin User",
        activated=True,
        is_admin=True,
        flush=True,
    )
    Session.flush()
    return user


def login_admin(flask_client, admin_user: User = None) -> User:
    """Login as an admin user."""
    if not admin_user:
        admin_user = create_admin_user()

    r = flask_client.post(
        url_for("auth.login"),
        data={"email": admin_user.email, "password": "password"},
        follow_redirects=True,
    )
    assert r.status_code == 200
    return admin_user


# ============================================================================
# Email Search Tests
# ============================================================================


def test_email_search_page_loads(flask_client):
    """Test that the email search page loads without errors."""
    login_admin(flask_client)

    r = flask_client.get(url_for("admin.email_search.index"))
    assert r.status_code == 200
    assert b"Email Search" in r.data


def test_email_search_empty_query(flask_client):
    """Test that empty query shows the search form."""
    login_admin(flask_client)

    r = flask_client.get(url_for("admin.email_search.index"))
    assert r.status_code == 200
    assert b"Search Query" in r.data


def test_email_search_user_by_email(flask_client):
    """Test searching for a user by their exact email."""
    login_admin(flask_client)

    # Create a test user to search for
    test_user = create_new_user(email=f"searchtest_{random_token(8)}@example.com")
    Session.commit()

    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={"query": test_user.email, "search_type": "email"},
    )
    assert r.status_code == 200
    assert test_user.email.encode() in r.data
    assert b"Account Information" in r.data


def test_email_search_user_by_id(flask_client):
    """Test searching for a user by their ID."""
    login_admin(flask_client)

    # Create a test user to search for
    test_user = create_new_user()
    Session.commit()

    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={"query": str(test_user.id), "search_type": "email"},
    )
    assert r.status_code == 200
    assert test_user.email.encode() in r.data


def test_email_search_no_regex_fallback(flask_client):
    """Test that email search does NOT perform regex search, only exact matches."""
    login_admin(flask_client)

    # Create test users with similar emails
    unique_id = random_token(6)
    create_new_user(email=f"regextest_{unique_id}_001@example.com")
    create_new_user(email=f"regextest_{unique_id}_002@example.com")
    Session.commit()

    # Regex pattern should NOT match in email search (exact match only)
    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={
            "query": f"regextest_{unique_id}_.*@example.com",
            "search_type": "email",
        },
    )
    assert r.status_code == 200
    # Should show no results since email search only does exact matches
    assert b"No results found" in r.data


def test_email_search_mailbox(flask_client):
    """Test searching for a mailbox by email."""
    login_admin(flask_client)

    # Create a user with a mailbox (use unique email to avoid collisions)
    test_user = create_new_user()
    mailbox_email = f"testmailbox_{random_token(8)}@example.com"
    mailbox = Mailbox.create(
        user_id=test_user.id,
        email=mailbox_email,
        verified=True,
        flush=True,
    )
    Session.commit()

    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={"query": mailbox.email, "search_type": "email"},
    )
    assert r.status_code == 200
    assert mailbox.email.encode() in r.data
    # Should also show the user info
    assert test_user.email.encode() in r.data


def test_email_search_partner_user(flask_client):
    """Test searching for a partner user."""
    login_admin(flask_client)

    # Create a user linked to a partner
    test_user = create_new_user()
    partner = get_proton_partner()
    partner_user = PartnerUser.create(
        partner_id=partner.id,
        user_id=test_user.id,
        external_user_id=random_token(10),
        partner_email="partner@proton.me",
        flush=True,
    )
    Session.commit()

    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={"query": partner_user.partner_email, "search_type": "email"},
    )
    assert r.status_code == 200
    assert partner_user.partner_email.encode() in r.data


def test_email_search_no_results(flask_client):
    """Test that searching for non-existent email shows no results message."""
    login_admin(flask_client)

    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={"query": "nonexistent@nowhere.com", "search_type": "email"},
    )
    assert r.status_code == 200
    assert b"No results found" in r.data


def test_email_search_user_with_subscription(flask_client):
    """Test that user subscription details are displayed correctly."""
    login_admin(flask_client)

    # Create a user with a manual subscription
    test_user = create_new_user(email=f"subtest_{random_token(8)}@example.com")
    ManualSubscription.create(
        user_id=test_user.id,
        end_at=arrow.now().shift(months=1),
        comment="Test subscription",
        flush=True,
    )
    Session.commit()

    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={"query": test_user.email, "search_type": "email"},
    )
    assert r.status_code == 200
    assert b"Manual" in r.data  # Subscription type badge
    assert b"Subscription" in r.data  # Subscription section header


def test_email_search_user_with_audit_logs(flask_client):
    """Test that user audit logs are displayed."""
    login_admin(flask_client)

    # Create a user with audit log
    test_user = create_new_user(email=f"auditlog_{random_token(8)}@example.com")
    UserAuditLog.create(
        user_id=test_user.id,
        user_email=test_user.email,
        action="test_action",
        message="Test audit log message",
        flush=True,
    )
    Session.commit()

    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={"query": test_user.email, "search_type": "email"},
    )
    assert r.status_code == 200
    assert b"User Audit Log" in r.data
    assert b"test_action" in r.data


def test_email_search_user_with_abuse_logs(flask_client):
    """Test that abuse audit logs are displayed."""
    login_admin(flask_client)

    # Create a user with abuse log
    test_user = create_new_user(email=f"abusetest_{random_token(8)}@example.com")
    AbuserAuditLog.create(
        user_id=test_user.id,
        action="mark_abuser",
        message="Test abuse log message",
        flush=True,
    )
    Session.commit()

    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={"query": test_user.email, "search_type": "email"},
    )
    assert r.status_code == 200
    assert b"Abuse Audit Log" in r.data
    assert b"mark_abuser" in r.data


# ============================================================================
# Alias Search Tests
# ============================================================================


def test_alias_search_page_loads(flask_client):
    """Test that alias search works."""
    login_admin(flask_client)

    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={"search_type": "alias"},
    )
    assert r.status_code == 200


def test_alias_search_by_email(flask_client):
    """Test searching for an alias by exact email."""
    login_admin(flask_client)

    # Create a user with an alias
    test_user = create_new_user()
    alias = Alias.create(
        user_id=test_user.id,
        email="testalias@sl.lan",
        mailbox_id=test_user.default_mailbox_id,
        flush=True,
    )
    Session.commit()

    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={"query": alias.email, "search_type": "alias"},
    )
    assert r.status_code == 200
    assert alias.email.encode() in r.data
    # Should also show the alias owner
    assert test_user.email.encode() in r.data


def test_alias_search_no_regex_support(flask_client):
    """Test that alias search only supports exact match, not regex patterns."""
    login_admin(flask_client)

    # Create a user with aliases
    test_user = create_new_user()
    Alias.create(
        user_id=test_user.id,
        email="regex_alias_001@sl.lan",
        mailbox_id=test_user.default_mailbox_id,
        flush=True,
    )
    Alias.create(
        user_id=test_user.id,
        email="regex_alias_002@sl.lan",
        mailbox_id=test_user.default_mailbox_id,
        flush=True,
    )
    Session.commit()

    # Regex pattern should not match - alias search only supports exact match
    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={"query": "regex_alias_.*@sl.lan", "search_type": "alias"},
    )
    assert r.status_code == 200
    # Should show no results since regex is not supported
    assert b"No results found" in r.data
    assert b"Regex Match" not in r.data


def test_alias_search_deleted_alias(flask_client):
    """Test searching for a deleted alias."""
    login_admin(flask_client)

    # Create a user with an alias and then delete it to create a deleted alias
    test_user = create_new_user()
    alias_email = f"to_be_deleted_{random_token(8)}@sl.lan"
    alias = Alias.create(
        user_id=test_user.id,
        email=alias_email,
        mailbox_id=test_user.default_mailbox_id,
        flush=True,
    )
    Session.commit()

    # Import delete_alias to properly delete
    from app.alias_delete import delete_alias

    delete_alias(alias, test_user)

    # Now search for the deleted alias
    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={"query": alias_email, "search_type": "alias"},
    )
    assert r.status_code == 200
    assert alias_email.encode() in r.data
    assert b"Deleted Alias" in r.data


def test_alias_search_no_results(flask_client):
    """Test that searching for non-existent alias shows no results."""
    login_admin(flask_client)

    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={"query": "nonexistent@sl.lan", "search_type": "alias"},
    )
    assert r.status_code == 200
    assert b"No results found" in r.data


# ============================================================================
# Access Control Tests
# ============================================================================


def test_email_search_requires_admin(flask_client):
    """Test that non-admin users cannot access email search."""
    # Login as regular user (not admin)
    regular_user = create_new_user()
    flask_client.post(
        url_for("auth.login"),
        data={"email": regular_user.email, "password": "password"},
        follow_redirects=True,
    )

    # Without follow_redirects, check for 302 redirect
    r = flask_client.get(url_for("admin.email_search.index"))
    # Should be redirected (302) to dashboard
    assert r.status_code == 302
    # The redirect should be to dashboard, not to admin
    assert "/admin" not in r.location or "dashboard" in r.location


def test_email_search_requires_login(flask_client):
    """Test that unauthenticated users cannot access email search."""
    r = flask_client.get(
        url_for("admin.email_search.index"),
        follow_redirects=True,
    )
    # Should be redirected to login
    assert b"login" in r.data.lower() or r.status_code in [302, 403]


# ============================================================================
# Search Type Toggle Tests
# ============================================================================


def test_search_type_defaults_to_email(flask_client):
    """Test that search type defaults to email."""
    login_admin(flask_client)

    r = flask_client.get(url_for("admin.email_search.index"))
    assert r.status_code == 200
    # Check that email option is checked (radio button)
    assert b'value="email" checked' in r.data


def test_search_type_preserves_alias_selection(flask_client):
    """Test that search type selection is preserved in the form."""
    login_admin(flask_client)

    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={"query": "test", "search_type": "alias"},
    )
    assert r.status_code == 200
    # Check that alias option is checked (radio button)
    assert b'value="alias" checked' in r.data


# ============================================================================
# Mark/Unmark Abuser Tests
# ============================================================================


def test_mark_abuser_button_displayed(flask_client):
    """Test that the mark abuser button is displayed for non-disabled users."""
    login_admin(flask_client)

    # Create a normal user
    test_user = create_new_user()
    Session.commit()

    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={"query": test_user.email, "search_type": "email"},
    )
    assert r.status_code == 200
    # Check for mark abuser button
    assert b"Mark as Abuser" in r.data
    assert b"markAbuserModal" in r.data


def test_unmark_abuser_button_displayed(flask_client):
    """Test that the unmark abuser button is displayed for disabled users."""
    login_admin(flask_client)

    # Create a disabled user
    test_user = create_new_user()
    test_user.disabled = True
    Session.commit()

    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={"query": test_user.email, "search_type": "email"},
    )
    assert r.status_code == 200
    # Check for unmark abuser button
    assert b"Unmark as Abuser" in r.data
    assert b"unmarkAbuserModal" in r.data


def test_mark_abuser_success(flask_client):
    """Test that marking a user as abuser works."""
    login_admin(flask_client)

    # Create a normal user
    test_user = create_new_user()
    Session.commit()
    user_id = test_user.id

    assert not test_user.disabled

    # Mark user as abuser
    r = flask_client.post(
        url_for("admin.email_search.mark_abuser"),
        data={"user_id": user_id, "note": "Test abuse reason"},
        follow_redirects=True,
    )
    assert r.status_code == 200

    # Refresh user from database
    Session.expire_all()
    test_user = User.get(user_id)
    assert test_user.disabled

    # Check for abuse audit log
    abuse_log = AbuserAuditLog.filter_by(user_id=user_id).first()
    assert abuse_log is not None
    assert "Test abuse reason" in abuse_log.message


def test_mark_abuser_requires_note(flask_client):
    """Test that marking a user as abuser requires a note."""
    login_admin(flask_client)

    # Create a normal user
    test_user = create_new_user()
    Session.commit()

    # Try to mark user without a note
    r = flask_client.post(
        url_for("admin.email_search.mark_abuser"),
        data={"user_id": test_user.id, "note": ""},
        follow_redirects=True,
    )
    assert r.status_code == 200
    # User should still be enabled
    Session.expire_all()
    test_user = User.get(test_user.id)
    assert not test_user.disabled


def test_unmark_abuser_success(flask_client):
    """Test that unmarking a user as abuser works."""
    login_admin(flask_client)

    # Create a disabled user
    test_user = create_new_user()
    test_user.disabled = True
    Session.commit()
    user_id = test_user.id

    assert test_user.disabled

    # Unmark user as abuser
    r = flask_client.post(
        url_for("admin.email_search.unmark_abuser"),
        data={"user_id": user_id, "note": "Test unmark reason"},
        follow_redirects=True,
    )
    assert r.status_code == 200

    # Refresh user from database
    Session.expire_all()
    test_user = User.get(user_id)
    assert not test_user.disabled

    # Check for abuse audit log
    abuse_log = (
        AbuserAuditLog.filter_by(user_id=user_id)
        .order_by(AbuserAuditLog.created_at.desc())
        .first()
    )
    assert abuse_log is not None
    assert "Test unmark reason" in abuse_log.message


def test_unmark_abuser_requires_note(flask_client):
    """Test that unmarking a user as abuser requires a note."""
    login_admin(flask_client)

    # Create a disabled user
    test_user = create_new_user()
    test_user.disabled = True
    Session.commit()

    # Try to unmark user without a note
    r = flask_client.post(
        url_for("admin.email_search.unmark_abuser"),
        data={"user_id": test_user.id, "note": ""},
        follow_redirects=True,
    )
    assert r.status_code == 200
    # User should still be disabled
    Session.expire_all()
    test_user = User.get(test_user.id)
    assert test_user.disabled


# ============================================================================
# Custom Domains Display Tests
# ============================================================================


def test_email_search_shows_custom_domains(flask_client):
    """Test that custom domains are displayed for a user in email search."""
    from app.models import CustomDomain

    login_admin(flask_client)

    # Create a user with a custom domain
    test_user = create_new_user()
    domain_name = f"domain-{random_token(8)}.com"
    domain = CustomDomain.create(
        user_id=test_user.id,
        domain=domain_name,
        ownership_verified=True,
        verified=True,
        flush=True,
    )
    Session.commit()

    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={"query": test_user.email, "search_type": "email"},
    )
    assert r.status_code == 200
    # Should show the custom domains section
    assert b"Custom Domains" in r.data
    # Should show the domain name
    assert domain.domain.encode() in r.data
    # Should have link to custom domain search
    assert b"custom_domain_search" in r.data


def test_email_search_shows_domain_alias_counts(flask_client):
    """Test that alias counts are displayed for custom domains."""
    from app.models import CustomDomain

    login_admin(flask_client)

    # Create a user with a custom domain and aliases
    test_user = create_new_user()
    domain_name = f"aliascount-{random_token(8)}.com"
    domain = CustomDomain.create(
        user_id=test_user.id,
        domain=domain_name,
        ownership_verified=True,
        verified=True,
        flush=True,
    )

    # Create an alias for the domain
    alias_email = f"alias@{domain_name}"
    Alias.create(
        user_id=test_user.id,
        email=alias_email,
        mailbox_id=test_user.default_mailbox_id,
        custom_domain_id=domain.id,
        flush=True,
    )
    Session.commit()

    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={"query": test_user.email, "search_type": "email"},
    )
    assert r.status_code == 200
    # Should show the aliases column in the custom domains table
    assert b"Aliases" in r.data
    assert b"Deleted" in r.data


# ============================================================================
# Regex Search Tests
# ============================================================================


def test_regex_search_does_not_search_aliases(flask_client):
    """Test that regex search does NOT search aliases."""
    login_admin(flask_client)

    # Create test aliases with similar patterns
    test_user = create_new_user()
    unique_id = random_token(8)
    Alias.create(
        user_id=test_user.id,
        email=f"regextest_{unique_id}_001@sl.lan",
        mailbox_id=test_user.default_mailbox_id,
        flush=True,
    )
    Alias.create(
        user_id=test_user.id,
        email=f"regextest_{unique_id}_002@sl.lan",
        mailbox_id=test_user.default_mailbox_id,
        flush=True,
    )
    Session.commit()

    # Regex search should NOT find aliases
    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={
            "query": f"regextest_{unique_id}_.*@sl.lan",
            "search_type": "regex",
        },
    )
    assert r.status_code == 200
    # Should not find aliases in regex search
    assert b"No results found" in r.data


def test_regex_search_users(flask_client):
    """Test regex search for users."""
    login_admin(flask_client)

    # Create test users with similar emails
    unique_id = random_token(8)
    create_new_user(email=f"regexuser_{unique_id}_001@example.com")
    create_new_user(email=f"regexuser_{unique_id}_002@example.com")
    Session.commit()

    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={
            "query": f"regexuser_{unique_id}_.*@example.com",
            "search_type": "regex",
        },
    )
    assert r.status_code == 200
    assert f"regexuser_{unique_id}_001@example.com".encode() in r.data
    assert f"regexuser_{unique_id}_002@example.com".encode() in r.data


def test_regex_search_mailboxes(flask_client):
    """Test regex search for mailboxes."""
    login_admin(flask_client)

    # Create test mailboxes with similar emails
    test_user = create_new_user()
    unique_id = random_token(8)
    Mailbox.create(
        user_id=test_user.id,
        email=f"regexmailbox_{unique_id}_001@example.com",
        verified=True,
        flush=True,
    )
    Mailbox.create(
        user_id=test_user.id,
        email=f"regexmailbox_{unique_id}_002@example.com",
        verified=True,
        flush=True,
    )
    Session.commit()

    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={
            "query": f"regexmailbox_{unique_id}_.*@example.com",
            "search_type": "regex",
        },
    )
    assert r.status_code == 200
    assert f"regexmailbox_{unique_id}_001@example.com".encode() in r.data
    assert f"regexmailbox_{unique_id}_002@example.com".encode() in r.data


def test_regex_search_across_multiple_tables(flask_client):
    """Test that regex search returns results from user and mailbox tables."""
    login_admin(flask_client)

    # Create test data across different tables
    unique_id = random_token(8)

    # Create user
    test_user = create_new_user(email=f"alltest_{unique_id}@example.com")

    # Create mailbox
    Mailbox.create(
        user_id=test_user.id,
        email=f"alltest_{unique_id}_mailbox@example.com",
        verified=True,
        flush=True,
    )
    Session.commit()

    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={
            "query": f"alltest_{unique_id}.*",
            "search_type": "regex",
        },
    )
    assert r.status_code == 200
    # Should show results from user and mailbox tables
    assert f"alltest_{unique_id}@example.com".encode() in r.data
    assert f"alltest_{unique_id}_mailbox@example.com".encode() in r.data


def test_regex_search_radio_button_present(flask_client):
    """Test that the regex radio button is present on the page."""
    login_admin(flask_client)

    r = flask_client.get(url_for("admin.email_search.index"))
    assert r.status_code == 200
    assert b'value="regex"' in r.data
    assert b"Regex" in r.data


def test_regex_search_type_preserved(flask_client):
    """Test that regex search type is preserved in the form."""
    login_admin(flask_client)

    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={"query": "test.*", "search_type": "regex"},
    )
    assert r.status_code == 200
    # Check that regex option is checked (radio button)
    assert b'value="regex" checked' in r.data


def test_regex_search_no_results(flask_client):
    """Test that regex search with no matches shows no results message."""
    login_admin(flask_client)

    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={
            "query": "nonexistent_regex_pattern_.*",
            "search_type": "regex",
        },
    )
    assert r.status_code == 200
    assert b"No results found" in r.data
    assert b"user/mailbox/partner emails (regex search)" in r.data


# ============================================================================
# Disable 2FA Tests
# ============================================================================


def _enable_totp(user: User) -> User:
    """Enable TOTP on a user."""
    user.enable_otp = True
    user.otp_secret = random_token(16)
    return user


def _enable_fido(user: User) -> User:
    """Enable FIDO on a user and create a FIDO credential entry."""
    user.fido_uuid = random_token(16)
    Session.flush()
    Fido.create(
        credential_id=random_token(32),
        uuid=user.fido_uuid,
        public_key=random_token(64),
        sign_count=0,
        name="Test Key",
        user_id=user.id,
        flush=True,
    )
    return user


def test_disable_2fa_totp_only(flask_client):
    """Test that disabling 2FA removes TOTP for a user with only TOTP enabled."""
    login_admin(flask_client)

    user = create_new_user()
    _enable_totp(user)
    Session.commit()
    user_id = user.id

    assert user.enable_otp is True

    r = flask_client.post(
        url_for("admin.email_search.disable_2fa"),
        data={"user_id": user_id},
        follow_redirects=True,
    )
    assert r.status_code == 200

    Session.expire_all()
    user = User.get(user_id)
    assert user.enable_otp is False
    assert user.otp_secret is None
    assert user.fido_uuid is None


def test_disable_2fa_fido_only(flask_client):
    """Test that disabling 2FA removes FIDO credentials for a user with only FIDO enabled."""
    login_admin(flask_client)

    user = create_new_user()
    _enable_fido(user)
    Session.commit()
    user_id = user.id

    assert user.fido_uuid is not None
    assert Session.query(Fido).filter(Fido.user_id == user_id).count() == 1

    r = flask_client.post(
        url_for("admin.email_search.disable_2fa"),
        data={"user_id": user_id},
        follow_redirects=True,
    )
    assert r.status_code == 200

    Session.expire_all()
    user = User.get(user_id)
    assert user.fido_uuid is None
    assert user.enable_otp is False
    assert Session.query(Fido).filter(Fido.user_id == user_id).count() == 0


def test_disable_2fa_totp_and_fido(flask_client):
    """Test that disabling 2FA removes both TOTP and FIDO when both are enabled."""
    login_admin(flask_client)

    user = create_new_user()
    _enable_totp(user)
    _enable_fido(user)
    Session.commit()
    user_id = user.id

    assert user.enable_otp is True
    assert user.fido_uuid is not None

    r = flask_client.post(
        url_for("admin.email_search.disable_2fa"),
        data={"user_id": user_id},
        follow_redirects=True,
    )
    assert r.status_code == 200

    Session.expire_all()
    user = User.get(user_id)
    assert user.enable_otp is False
    assert user.otp_secret is None
    assert user.fido_uuid is None
    assert Session.query(Fido).filter(Fido.user_id == user_id).count() == 0


def test_disable_2fa_does_not_affect_other_users(flask_client):
    """Test that disabling 2FA for one user does not affect other users' 2FA settings."""
    login_admin(flask_client)

    # Target user whose 2FA will be disabled
    target_user = create_new_user()
    _enable_totp(target_user)
    _enable_fido(target_user)

    # Bystander user with TOTP
    totp_user = create_new_user()
    _enable_totp(totp_user)

    # Bystander user with FIDO
    fido_user = create_new_user()
    _enable_fido(fido_user)

    # Bystander user with both
    both_user = create_new_user()
    _enable_totp(both_user)
    _enable_fido(both_user)

    Session.commit()

    totp_user_id = totp_user.id
    fido_user_id = fido_user.id
    both_user_id = both_user.id
    fido_user_fido_uuid = fido_user.fido_uuid
    both_user_fido_uuid = both_user.fido_uuid

    r = flask_client.post(
        url_for("admin.email_search.disable_2fa"),
        data={"user_id": target_user.id},
        follow_redirects=True,
    )
    assert r.status_code == 200

    Session.expire_all()

    # TOTP-only bystander is untouched
    totp_user = User.get(totp_user_id)
    assert totp_user.enable_otp is True
    assert totp_user.otp_secret is not None

    # FIDO-only bystander is untouched
    fido_user = User.get(fido_user_id)
    assert fido_user.fido_uuid == fido_user_fido_uuid
    assert Session.query(Fido).filter(Fido.uuid == fido_user_fido_uuid).count() == 1

    # Both-enabled bystander is untouched
    both_user = User.get(both_user_id)
    assert both_user.enable_otp is True
    assert both_user.otp_secret is not None
    assert both_user.fido_uuid == both_user_fido_uuid
    assert Session.query(Fido).filter(Fido.uuid == both_user_fido_uuid).count() == 1


def test_disable_2fa_creates_audit_log(flask_client):
    """Test that disabling 2FA creates an admin audit log entry."""
    login_admin(flask_client)

    user = create_new_user()
    _enable_totp(user)
    Session.commit()
    user_id = user.id

    r = flask_client.post(
        url_for("admin.email_search.disable_2fa"),
        data={"user_id": user_id},
        follow_redirects=True,
    )
    assert r.status_code == 200

    audit = (
        Session.query(AdminAuditLog)
        .filter_by(
            model="User",
            model_id=user_id,
            action=AuditLogActionEnum.disable_2fa.value,
        )
        .order_by(AdminAuditLog.created_at.desc())
        .first()
    )
    assert audit is not None
    assert "TOTP" in audit.data["disabled_methods"]


def test_disable_2fa_invalid_user_id(flask_client):
    """Test that an invalid user_id returns an error."""
    login_admin(flask_client)

    r = flask_client.post(
        url_for("admin.email_search.disable_2fa"),
        data={"user_id": "not_a_number"},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert b"Invalid user_id" in r.data


def test_disable_2fa_nonexistent_user(flask_client):
    """Test that a non-existent user_id returns an error."""
    login_admin(flask_client)

    r = flask_client.post(
        url_for("admin.email_search.disable_2fa"),
        data={"user_id": 999999999},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert b"User not found" in r.data


def test_disable_2fa_missing_user_id(flask_client):
    """Test that a missing user_id returns an error."""
    login_admin(flask_client)

    r = flask_client.post(
        url_for("admin.email_search.disable_2fa"),
        data={},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert b"Missing user_id" in r.data
