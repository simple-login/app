from flask import url_for

from app.db import Session
from app.models import Mailbox
from tests.utils import login


def test_create_mailbox(flask_client):
    login(flask_client)

    r = flask_client.post(
        "/api/mailboxes",
        json={"email": "mailbox@gmail.com"},
    )

    assert r.status_code == 201

    assert r.json["email"] == "mailbox@gmail.com"
    assert r.json["verified"] is False
    assert r.json["id"] > 0
    assert r.json["default"] is False
    assert r.json["nb_alias"] == 0

    # invalid email address
    r = flask_client.post(
        "/api/mailboxes",
        json={"email": "gmail.com"},
    )

    assert r.status_code == 400
    assert r.json == {"error": "gmail.com invalid"}


def test_create_mailbox_fail_for_free_user(flask_client):
    user = login(flask_client)
    user.trial_end = None
    Session.commit()

    r = flask_client.post(
        "/api/mailboxes",
        json={"email": "mailbox@gmail.com"},
    )

    assert r.status_code == 400
    assert r.json == {"error": "Only premium plan can add additional mailbox"}


def test_delete_mailbox(flask_client):
    user = login(flask_client)

    # create a mailbox
    mb = Mailbox.create(user_id=user.id, email="mb@gmail.com")
    Session.commit()

    r = flask_client.delete(
        f"/api/mailboxes/{mb.id}",
    )

    assert r.status_code == 200


def test_delete_default_mailbox(flask_client):
    user = login(flask_client)

    # assert user cannot delete the default mailbox
    r = flask_client.delete(
        url_for("api.delete_mailbox", mailbox_id=user.default_mailbox_id),
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
    Session.commit()

    r = flask_client.put(
        f"/api/mailboxes/{mb.id}",
        json={"default": True},
    )

    assert r.status_code == 400
    assert r.json == {"error": "Unverified mailbox cannot be used as default mailbox"}


def test_update_mailbox_email(flask_client):
    user = login(flask_client)

    # create a mailbox
    mb = Mailbox.create(user_id=user.id, email="mb@gmail.com")
    Session.commit()

    r = flask_client.put(
        f"/api/mailboxes/{mb.id}",
        json={"email": "new-email@gmail.com"},
    )

    assert r.status_code == 200

    mb = Mailbox.get(mb.id)
    assert mb.new_email == "new-email@gmail.com"


def test_cancel_mailbox_email_change(flask_client):
    user = login(flask_client)

    # create a mailbox
    mb = Mailbox.create(user_id=user.id, email="mb@gmail.com")
    Session.commit()

    # update mailbox email
    r = flask_client.put(
        f"/api/mailboxes/{mb.id}",
        json={"email": "new-email@gmail.com"},
    )
    assert r.status_code == 200

    mb = Mailbox.get(mb.id)
    assert mb.new_email == "new-email@gmail.com"

    # cancel mailbox email change
    r = flask_client.put(
        url_for("api.delete_mailbox", mailbox_id=mb.id),
        json={"cancel_email_change": True},
    )
    assert r.status_code == 200

    mb = Mailbox.get(mb.id)
    assert mb.new_email is None


def test_get_mailboxes(flask_client):
    user = login(flask_client)

    Mailbox.create(user_id=user.id, email="m1@example.com", verified=True)
    Mailbox.create(user_id=user.id, email="m2@example.com", verified=False)
    Session.commit()

    r = flask_client.get(
        "/api/mailboxes",
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
    Session.commit()

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
