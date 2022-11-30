from flask import url_for

from app.db import Session
from app.utils import canonicalize_email, random_string
from tests.utils import create_new_user, random_email


def test_unactivated_user_login(flask_client):
    user = create_new_user()
    user.activated = False
    Session.commit()

    r = flask_client.post(
        url_for("auth.login"),
        data={"email": user.email, "password": "password"},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert (
        b"Please check your inbox for the activation email. You can also have this email re-sent"
        in r.data
    )


def test_non_canonical_login(flask_client):
    email = random_email()
    email = f"pre.{email}"
    name = f"NAME-{random_string(10)}"
    user = create_new_user(email, name)
    Session.commit()

    r = flask_client.post(
        url_for("auth.login"),
        data={"email": user.email, "password": "password"},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert name.encode("utf-8") in r.data

    canonical_email = canonicalize_email(email)
    assert canonical_email != email

    r = flask_client.post(
        url_for("auth.login"),
        data={"email": canonical_email, "password": "password"},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert name.encode("utf-8") in r.data
