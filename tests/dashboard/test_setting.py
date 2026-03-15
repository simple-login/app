from unittest.mock import patch

from flask import url_for

from app import config
from app.db import Session
from app.models import EmailChange, BlockedDomain
from app.utils import canonicalize_email
from tests.utils import login, random_email, create_new_user


def test_setup_done(flask_client):
    config.SKIP_MX_LOOKUP_ON_CHECK = True
    user = create_new_user()
    login(flask_client, user)
    noncanonical_email = f"nonca.{random_email()}"

    r = flask_client.post(
        url_for("dashboard.account_setting"),
        data={
            "form-name": "update-email",
            "email": noncanonical_email,
        },
        follow_redirects=True,
    )

    assert r.status_code == 200
    email_change = EmailChange.get_by(user_id=user.id)
    assert email_change is not None
    assert email_change.new_email == canonicalize_email(noncanonical_email)
    config.SKIP_MX_LOOKUP_ON_CHECK = False


def test_add_blocked_domain_none(flask_client):
    user = create_new_user()
    login(flask_client, user)

    # Missing domain-name
    r = flask_client.post(
        url_for("dashboard.setting"),
        data={
            "form-name": "blocked-domains-add",
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert BlockedDomain.filter_by(user_id=user.id).count() == 0


def test_add_blocked_domain_empty(flask_client):
    user = create_new_user()
    login(flask_client, user)

    # Empty domain-name
    r = flask_client.post(
        url_for("dashboard.setting"),
        data={
            "form-name": "blocked-domains-add",
            "domain-name": "",
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert BlockedDomain.filter_by(user_id=user.id).count() == 0


def test_add_blocked_domain_success(flask_client):
    user = create_new_user()
    login(flask_client, user)

    r = flask_client.post(
        url_for("dashboard.setting"),
        data={
            "form-name": "blocked-domains-add",
            "domain-name": " ExAmple.COM ",
        },
        follow_redirects=True,
    )
    assert r.status_code == 200

    blocked_domains = BlockedDomain.filter_by(user_id=user.id).all()
    assert len(blocked_domains) == 1
    assert blocked_domains[0].domain == "example.com"


def test_remove_blocked_domain_no_id(flask_client):
    user = create_new_user()

    login(flask_client, user)

    # Missing domain_id
    with patch("app.dashboard.views.setting.BlockedDomain.delete") as mock_delete:
        r = flask_client.post(
            url_for("dashboard.setting"),
            data={
                "form-name": "blocked-domains-remove",
                "domain_name": "example.com",
            },
            follow_redirects=True,
        )
        assert r.status_code == 200
        mock_delete.assert_not_called()


def test_remove_blocked_domain_invalid_id(flask_client):
    user = create_new_user()
    login(flask_client, user)

    # Invalid domain_id
    with patch("app.dashboard.views.setting.BlockedDomain.delete") as mock_delete:
        r = flask_client.post(
            url_for("dashboard.setting"),
            data={
                "form-name": "blocked-domains-remove",
                "domain_id": 9999,
                "domain_name": "example.com",
            },
            follow_redirects=True,
        )
        assert r.status_code == 200
        mock_delete.assert_not_called()


def test_remove_blocked_domain_success(flask_client):
    user = create_new_user()
    bd = BlockedDomain.create(user_id=user.id, domain="example.com")
    Session.commit()

    login(flask_client, user)

    r = flask_client.post(
        url_for("dashboard.setting"),
        data={
            "form-name": "blocked-domains-remove",
            "domain_id": bd.id,
            "domain_name": bd.domain,
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert BlockedDomain.get(bd.id) is None


def test_remove_blocked_domain_not_owned(flask_client):
    user1 = create_new_user()
    user2 = create_new_user()

    bd = BlockedDomain.create(user_id=user1.id, domain="example.com")
    Session.commit()

    login(flask_client, user2)

    # Try to remove user1's blocked domain as user2
    r = flask_client.post(
        url_for("dashboard.setting"),
        data={
            "form-name": "blocked-domains-remove",
            "domain_id": bd.id,
            "domain_name": "example.com",
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert BlockedDomain.get(bd.id) is not None


def test_remove_blocked_domain_name_missing(flask_client):
    user = create_new_user()
    bd = BlockedDomain.create(user_id=user.id, domain="example.com")
    Session.commit()

    login(flask_client, user)

    # Missing domain_name
    with patch("app.dashboard.views.setting.BlockedDomain.delete") as mock_delete:
        r = flask_client.post(
            url_for("dashboard.setting"),
            data={
                "form-name": "blocked-domains-remove",
                "domain_id": bd.id,
            },
            follow_redirects=True,
        )
        assert r.status_code == 200
        # Check that it didn't delete the domain
        assert BlockedDomain.get(bd.id) is not None
        mock_delete.assert_not_called()
