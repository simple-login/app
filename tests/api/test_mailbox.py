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


def test_delete_mailbox(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    # create a mailbox
    mb = Mailbox.create(user_id=user.id, email="mb@gmail.com")
    db.session.commit()

    r = flask_client.delete(
        url_for("api.delete_mailbox", mailbox_id=mb.id),
        headers={"Authentication": api_key.code},
    )

    assert r.status_code == 200


def test_delete_default_mailbox(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    # assert user cannot delete the default mailbox
    r = flask_client.delete(
        url_for("api.delete_mailbox", mailbox_id=user.default_mailbox_id),
        headers={"Authentication": api_key.code},
    )

    assert r.status_code == 400


def test_set_mailbox_as_default(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    # create a mailbox
    mb = Mailbox.create(user_id=user.id, email="mb@gmail.com")
    db.session.commit()
    assert user.default_mailbox_id != mb.id

    r = flask_client.put(
        url_for("api.delete_mailbox", mailbox_id=mb.id),
        headers={"Authentication": api_key.code},
        json={"default": True},
    )

    assert r.status_code == 200

    mb = Mailbox.get(mb.id)
    assert user.default_mailbox_id == mb.id


def test_update_mailbox_email(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    # create a mailbox
    mb = Mailbox.create(user_id=user.id, email="mb@gmail.com")
    db.session.commit()

    r = flask_client.put(
        url_for("api.delete_mailbox", mailbox_id=mb.id),
        headers={"Authentication": api_key.code},
        json={"email": "new-email@gmail.com"},
    )

    assert r.status_code == 200

    mb = Mailbox.get(mb.id)
    assert mb.new_email == "new-email@gmail.com"


def test_cancel_mailbox_email_change(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    # create a mailbox
    mb = Mailbox.create(user_id=user.id, email="mb@gmail.com")
    db.session.commit()

    # update mailbox email
    r = flask_client.put(
        url_for("api.delete_mailbox", mailbox_id=mb.id),
        headers={"Authentication": api_key.code},
        json={"email": "new-email@gmail.com"},
    )
    assert r.status_code == 200

    mb = Mailbox.get(mb.id)
    assert mb.new_email == "new-email@gmail.com"

    # cancel mailbox email change
    r = flask_client.put(
        url_for("api.delete_mailbox", mailbox_id=mb.id),
        headers={"Authentication": api_key.code},
        json={"cancel_email_change": True},
    )
    assert r.status_code == 200

    mb = Mailbox.get(mb.id)
    assert mb.new_email is None
