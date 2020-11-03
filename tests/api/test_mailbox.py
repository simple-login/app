from flask import url_for

from app.extensions import db
from app.models import User, ApiKey, Mailbox
from tests.utils import login


def test_create_mailbox(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    r = flask_client.post(
        "/api/mailboxes",
        headers={"Authentication": api_key.code},
        json={"email": "mailbox@gmail.com"},
    )

    assert r.status_code == 201

    # {'creation_timestamp': 1604398668, 'default': False, 'email': 'mailbox@gmail.com', 'id': 2, 'nb_alias': 0, 'verified': False}
    assert r.json["email"] == "mailbox@gmail.com"
    assert r.json["verified"] is False
    assert r.json["id"] > 0
    assert r.json["default"] is False
    assert r.json["nb_alias"] == 0


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
        f"/api/mailboxes/{mb.id}",
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
    user = login(flask_client)

    mb = Mailbox.create(
        user_id=user.id, email="mb@gmail.com", verified=True, commit=True
    )
    assert user.default_mailbox_id != mb.id

    r = flask_client.put(
        f"/api/mailboxes/{mb.id}",
        json={"default": True},
    )

    assert r.status_code == 200
    assert user.default_mailbox_id == mb.id

    # <<< Cannot set an unverified mailbox as default >>>
    mb.verified = False
    db.session.commit()

    r = flask_client.put(
        f"/api/mailboxes/{mb.id}",
        json={"default": True},
    )

    assert r.status_code == 400
    assert r.json == {"error": "Unverified mailbox cannot be used as default mailbox"}


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
        f"/api/mailboxes/{mb.id}",
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
        f"/api/mailboxes/{mb.id}",
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


def test_get_mailboxes(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    Mailbox.create(user_id=user.id, email="m1@example.com", verified=True)
    Mailbox.create(user_id=user.id, email="m2@example.com", verified=False)
    db.session.commit()

    r = flask_client.get(
        "/api/mailboxes",
        headers={"Authentication": api_key.code},
    )
    assert r.status_code == 200
    # m2@example.com is not returned as it's not verified
    assert len(r.json["mailboxes"]) == 2

    for mb in r.json["mailboxes"]:
        assert "email" in mb
        assert "id" in mb
        assert "default" in mb
        assert "creation_timestamp" in mb
        assert "nb_alias" in mb
        assert "verified" in mb


def test_get_mailboxes_v2(flask_client):
    user = login(flask_client)

    Mailbox.create(user_id=user.id, email="m1@example.com", verified=True)
    Mailbox.create(user_id=user.id, email="m2@example.com", verified=False)
    db.session.commit()

    r = flask_client.get(
        "/api/v2/mailboxes",
    )
    assert r.status_code == 200
    # 3 mailboxes: the default, m1 and m2
    assert len(r.json["mailboxes"]) == 3

    for mb in r.json["mailboxes"]:
        assert "email" in mb
        assert "id" in mb
        assert "default" in mb
        assert "creation_timestamp" in mb
        assert "nb_alias" in mb
        assert "verified" in mb
