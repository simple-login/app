from flask import url_for

from app.extensions import db
from app.models import User


def login(flask_client) -> User:
    # create user, user is activated
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    r = flask_client.post(
        url_for("auth.login"),
        data={"email": "a@b.c", "password": "password"},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert b"/auth/logout" in r.data

    return user
