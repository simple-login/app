from flask import url_for

from app.db import Session
from app.email_utils import get_email_domain_part
from app.models import Mailbox
from tests.utils import login, random_domain


def test_add_domain_success(flask_client):
    user = login(flask_client)
    user.lifetime = True
    Session.commit()

    domain = random_domain()
    r = flask_client.post(
        url_for("dashboard.custom_domain"),
        data={"form-name": "create", "domain": domain},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert f"New domain {domain} is created".encode() in r.data


def test_add_domain_same_as_user_email(flask_client):
    """cannot add domain if user personal email uses this domain"""
    user = login(flask_client)
    user.lifetime = True
    Session.commit()

    r = flask_client.post(
        url_for("dashboard.custom_domain"),
        data={"form-name": "create", "domain": get_email_domain_part(user.email)},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert (
        b"You cannot add a domain that you are currently using for your personal email"
        in r.data
    )


def test_add_domain_used_in_mailbox(flask_client):
    """cannot add domain if it has been used in a verified mailbox"""
    user = login(flask_client)
    user.lifetime = True
    Session.commit()

    Mailbox.create(
        user_id=user.id, email="mailbox@new-domain.com", verified=True, commit=True
    )

    r = flask_client.post(
        url_for("dashboard.custom_domain"),
        data={"form-name": "create", "domain": "new-domain.com"},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert b"new-domain.com already used in a SimpleLogin mailbox" in r.data
