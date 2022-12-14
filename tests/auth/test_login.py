from flask import url_for

from app.db import Session
from app.utils import canonicalize_email, random_string
from tests.utils import create_new_user


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
    email = f"pre.{random_string(10)}@gmail.com"
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

    flask_client.get(url_for("auth.logout"))

    r = flask_client.post(
        url_for("auth.login"),
        data={"email": canonical_email, "password": "password"},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert name.encode("utf-8") not in r.data


def test_canonical_login_with_non_canonical_email(flask_client):
    suffix = f"{random_string(10)}@gmail.com"
    canonical_email = f"pre{suffix}"
    non_canonical_email = f"pre.{suffix}"
    name = f"NAME-{random_string(10)}"
    create_new_user(canonical_email, name)
    Session.commit()

    r = flask_client.post(
        url_for("auth.login"),
        data={"email": non_canonical_email, "password": "password"},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert name.encode("utf-8") in r.data

    flask_client.get(url_for("auth.logout"))

    r = flask_client.post(
        url_for("auth.login"),
        data={"email": canonical_email, "password": "password"},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert name.encode("utf-8") in r.data
