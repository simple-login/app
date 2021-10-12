from flask import url_for

from app.db import Session
from app.models import User


def test_unactivated_user_login(flask_client):
    """Start with a blank database."""

    # create user, user is not activated
    User.create(email="a@b.c", password="password", name="Test User")
    Session.commit()

    r = flask_client.post(
        url_for("auth.login"),
        data={"email": "a@b.c", "password": "password"},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert (
        b"Please check your inbox for the activation email. You can also have this email re-sent"
        in r.data
    )


def test_activated_user_login(flask_client):
    """Start with a blank database."""

    # create user, user is activated
    User.create(email="a@b.c", password="password", name="Test User", activated=True)
    Session.commit()

    r = flask_client.post(
        url_for("auth.login"),
        data={"email": "a@b.c", "password": "password"},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert b"/auth/logout" in r.data
