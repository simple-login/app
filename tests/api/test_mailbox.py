from flask import url_for

from flask import url_for

from app.extensions import db
from app.models import User, ApiKey, Mailbox


def test_create_mailbox(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    r = flask_client.post(
        url_for("api.create_mailbox"),
        headers={"Authentication": api_key.code},
        json={"email": "mailbox@gmail.com"},
    )

    assert r.status_code == 201
    assert r.json["email"] == "mailbox@gmail.com"
    assert r.json["verified"] is False
    assert r.json["id"] > 0
    assert r.json["default"] is False


