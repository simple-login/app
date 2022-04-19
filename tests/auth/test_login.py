from flask import url_for

from app.db import Session
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
