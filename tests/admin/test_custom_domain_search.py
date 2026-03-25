"""Tests for admin custom domain search functionality."""

from flask import url_for

from app.db import Session
from app.models import User, CustomDomain
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


def create_custom_domain(user: User, domain_name: str = None) -> CustomDomain:
    """Create a custom domain for testing."""
    if not domain_name:
        domain_name = f"test-{random_token(8)}.com"
    domain = CustomDomain.create(
        user_id=user.id,
        domain=domain_name,
        ownership_verified=True,
        verified=True,
        flush=True,
    )
    Session.flush()
    return domain


# ============================================================================
# Page Load Tests
# ============================================================================


def test_custom_domain_search_page_loads(flask_client):
    """Test that the custom domain search page loads without errors."""
    login_admin(flask_client)

    r = flask_client.get(url_for("admin.custom_domain_search.index"))
    assert r.status_code == 200
    assert b"Custom Domain Search" in r.data


def test_custom_domain_search_empty_query(flask_client):
    """Test that empty query shows the search form."""
    login_admin(flask_client)

    r = flask_client.get(url_for("admin.custom_domain_search.index"))
    assert r.status_code == 200
    assert b"Search Query" in r.data


# ============================================================================
# Search by Domain Tests
# ============================================================================


def test_custom_domain_search_by_domain_name(flask_client):
    """Test searching for a custom domain by exact domain name."""
    login_admin(flask_client)

    # Create a user with a custom domain
    test_user = create_new_user()
    domain_name = f"exact-{random_token(8)}.com"
    domain = create_custom_domain(test_user, domain_name)
    Session.commit()

    r = flask_client.get(
        url_for("admin.custom_domain_search.index"),
        query_string={"query": domain.domain},
    )
    assert r.status_code == 200
    assert domain.domain.encode() in r.data
    # Should show domain owner info
    assert test_user.email.encode() in r.data
    # Should show verification status
    assert b"Verification Status" in r.data


def test_custom_domain_search_by_user_email(flask_client):
    """Test searching for custom domains by user email."""
    login_admin(flask_client)

    # Create a user with multiple custom domains
    test_user = create_new_user(email=f"domainowner_{random_token(8)}@example.com")
    domain1 = create_custom_domain(test_user, f"domain1-{random_token(6)}.com")
    domain2 = create_custom_domain(test_user, f"domain2-{random_token(6)}.com")
    Session.commit()

    r = flask_client.get(
        url_for("admin.custom_domain_search.index"),
        query_string={"query": test_user.email},
    )
    assert r.status_code == 200
    assert domain1.domain.encode() in r.data
    assert domain2.domain.encode() in r.data


def test_custom_domain_search_by_user_id(flask_client):
    """Test searching for custom domains by user ID."""
    login_admin(flask_client)

    # Create a user with a custom domain
    test_user = create_new_user()
    domain = create_custom_domain(test_user, f"byid-{random_token(8)}.com")
    Session.commit()

    r = flask_client.get(
        url_for("admin.custom_domain_search.index"),
        query_string={"query": str(test_user.id)},
    )
    assert r.status_code == 200
    assert domain.domain.encode() in r.data


def test_custom_domain_search_by_regex(flask_client):
    """Test searching for custom domains by regex pattern."""
    login_admin(flask_client)

    # Create users with similar domain names
    unique_prefix = f"regex{random_token(4)}"
    user1 = create_new_user()
    user2 = create_new_user()
    create_custom_domain(user1, f"{unique_prefix}-001.com")
    create_custom_domain(user2, f"{unique_prefix}-002.com")
    Session.commit()

    r = flask_client.get(
        url_for("admin.custom_domain_search.index"),
        query_string={"query": f"{unique_prefix}-.*\\.com"},
    )
    assert r.status_code == 200
    # Should indicate regex match
    assert b"matching regex pattern" in r.data


def test_custom_domain_search_no_results(flask_client):
    """Test that searching for non-existent domain shows no results message."""
    login_admin(flask_client)

    r = flask_client.get(
        url_for("admin.custom_domain_search.index"),
        query_string={"query": "nonexistent-domain-xyz.com"},
    )
    assert r.status_code == 200
    assert b"No custom domains found" in r.data


# ============================================================================
# Domain Information Display Tests
# ============================================================================


def test_custom_domain_shows_user_link_to_email_search(flask_client):
    """Test that domain owner email links to email search."""
    login_admin(flask_client)

    test_user = create_new_user()
    domain = create_custom_domain(test_user)
    Session.commit()

    r = flask_client.get(
        url_for("admin.custom_domain_search.index"),
        query_string={"query": domain.domain},
    )
    assert r.status_code == 200
    # User email should be a link to email search
    assert test_user.email.encode() in r.data
    assert b"email_search" in r.data


def test_custom_domain_shows_verification_status(flask_client):
    """Test that verification status is displayed."""
    login_admin(flask_client)

    test_user = create_new_user()
    domain = CustomDomain.create(
        user_id=test_user.id,
        domain=f"unverified-{random_token(8)}.com",
        ownership_verified=False,
        verified=False,
        spf_verified=False,
        dkim_verified=False,
        flush=True,
    )
    Session.commit()

    r = flask_client.get(
        url_for("admin.custom_domain_search.index"),
        query_string={"query": domain.domain},
    )
    assert r.status_code == 200
    assert b"Ownership" in r.data
    assert b"MX" in r.data
    assert b"SPF" in r.data
    assert b"DKIM" in r.data


def test_custom_domain_shows_domain_info(flask_client):
    """Test that domain information is displayed."""
    login_admin(flask_client)

    test_user = create_new_user()
    domain = CustomDomain.create(
        user_id=test_user.id,
        domain=f"infotest-{random_token(8)}.com",
        ownership_verified=True,
        verified=True,
        catch_all=True,
        flush=True,
    )
    Session.commit()

    r = flask_client.get(
        url_for("admin.custom_domain_search.index"),
        query_string={"query": domain.domain},
    )
    assert r.status_code == 200
    assert b"Domain Information" in r.data
    assert b"Catch-All" in r.data


# ============================================================================
# Access Control Tests
# ============================================================================


def test_custom_domain_search_requires_admin(flask_client):
    """Test that non-admin users cannot access custom domain search."""
    # Login as regular user (not admin)
    regular_user = create_new_user()
    flask_client.post(
        url_for("auth.login"),
        data={"email": regular_user.email, "password": "password"},
        follow_redirects=True,
    )

    r = flask_client.get(url_for("admin.custom_domain_search.index"))
    assert r.status_code == 302


def test_custom_domain_search_requires_login(flask_client):
    """Test that unauthenticated users cannot access custom domain search."""
    r = flask_client.get(
        url_for("admin.custom_domain_search.index"),
        follow_redirects=True,
    )
    assert b"login" in r.data.lower() or r.status_code in [302, 403]


# ============================================================================
# User Without Domains Test
# ============================================================================


def test_custom_domain_search_user_without_domains(flask_client):
    """Test searching for a user that has no custom domains."""
    login_admin(flask_client)

    # Create a user without any custom domains
    test_user = create_new_user(email=f"nodomains_{random_token(8)}@example.com")
    Session.commit()

    r = flask_client.get(
        url_for("admin.custom_domain_search.index"),
        query_string={"query": test_user.email},
    )
    assert r.status_code == 200
    # Should show no domains found since user has no domains
    assert b"No custom domains found" in r.data
