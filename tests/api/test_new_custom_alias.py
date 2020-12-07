from flask import url_for

from app.alias_utils import delete_alias
from app.config import EMAIL_DOMAIN, MAX_NB_EMAIL_FREE_PLAN
from app.dashboard.views.custom_alias import signer
from app.extensions import db
from app.models import User, ApiKey, Alias, CustomDomain, Mailbox
from app.utils import random_word


def test_success(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    # create new alias with note
    word = random_word()
    r = flask_client.post(
        url_for("api.new_custom_alias", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
        json={
            "alias_prefix": "prefix",
            "alias_suffix": f".{word}@{EMAIL_DOMAIN}",
            "note": "test note",
        },
    )

    assert r.status_code == 201
    assert r.json["alias"] == f"prefix.{word}@{EMAIL_DOMAIN}"

    # assert returned field
    res = r.json
    assert "id" in res
    assert "email" in res
    assert "creation_date" in res
    assert "creation_timestamp" in res
    assert "nb_forward" in res
    assert "nb_block" in res
    assert "nb_reply" in res
    assert "enabled" in res
    assert "note" in res

    new_ge = Alias.get_by(email=r.json["alias"])
    assert new_ge.note == "test note"


def test_create_custom_alias_without_note(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    # create alias without note
    word = random_word()
    r = flask_client.post(
        url_for("api.new_custom_alias", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
        json={"alias_prefix": "prefix", "alias_suffix": f".{word}@{EMAIL_DOMAIN}"},
    )

    assert r.status_code == 201
    assert r.json["alias"] == f"prefix.{word}@{EMAIL_DOMAIN}"

    new_ge = Alias.get_by(email=r.json["alias"])
    assert new_ge.note is None


def test_out_of_quota(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    user.trial_end = None
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    # create MAX_NB_EMAIL_FREE_PLAN custom alias to run out of quota
    for _ in range(MAX_NB_EMAIL_FREE_PLAN):
        Alias.create_new(user, prefix="test")

    word = random_word()
    r = flask_client.post(
        url_for("api.new_custom_alias", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
        json={"alias_prefix": "prefix", "alias_suffix": f".{word}@{EMAIL_DOMAIN}"},
    )

    assert r.status_code == 400
    assert r.json == {
        "error": "You have reached the limitation of a free account with the maximum of 3 aliases, please upgrade your plan to create more aliases"
    }


def test_success_v2(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    # create new alias with note
    word = random_word()
    suffix = f".{word}@{EMAIL_DOMAIN}"
    suffix = signer.sign(suffix).decode()

    r = flask_client.post(
        url_for("api.new_custom_alias_v2", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
        json={
            "alias_prefix": "prefix",
            "signed_suffix": suffix,
            "note": "test note",
        },
    )

    assert r.status_code == 201
    assert r.json["alias"] == f"prefix.{word}@{EMAIL_DOMAIN}"

    # assert returned field
    res = r.json
    assert "id" in res
    assert "email" in res
    assert "creation_date" in res
    assert "creation_timestamp" in res
    assert "nb_forward" in res
    assert "nb_block" in res
    assert "nb_reply" in res
    assert "enabled" in res
    assert "note" in res

    new_ge = Alias.get_by(email=r.json["alias"])
    assert new_ge.note == "test note"


def test_cannot_create_alias_in_trash(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    # create a custom domain
    CustomDomain.create(user_id=user.id, domain="ab.cd", verified=True)
    db.session.commit()

    # create new alias with note
    suffix = "@ab.cd"
    suffix = signer.sign(suffix).decode()

    r = flask_client.post(
        url_for("api.new_custom_alias_v2", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
        json={
            "alias_prefix": "prefix",
            "signed_suffix": suffix,
            "note": "test note",
        },
    )

    # assert alias creation is successful
    assert r.status_code == 201
    assert r.json["alias"] == "prefix@ab.cd"

    # delete alias: it's going to be moved to ab.cd trash
    alias = Alias.get_by(email="prefix@ab.cd")
    assert alias.custom_domain_id
    delete_alias(alias, user)

    # try to create the same alias, will fail as the alias is in trash
    r = flask_client.post(
        url_for("api.new_custom_alias_v2", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
        json={
            "alias_prefix": "prefix",
            "signed_suffix": suffix,
            "note": "test note",
        },
    )
    assert r.status_code == 409


def test_success_v3(flask_client):
    user = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    # create another mailbox
    mb = Mailbox.create(user_id=user.id, email="abcd@gmail.com", verified=True)
    db.session.commit()

    # create new alias with note
    word = random_word()
    suffix = f".{word}@{EMAIL_DOMAIN}"
    suffix = signer.sign(suffix).decode()

    r = flask_client.post(
        url_for("api.new_custom_alias_v3", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
        json={
            "alias_prefix": "prefix",
            "signed_suffix": suffix,
            "note": "test note",
            "mailbox_ids": [user.default_mailbox_id, mb.id],
            "name": "your name",
        },
    )

    assert r.status_code == 201
    assert r.json["alias"] == f"prefix.{word}@{EMAIL_DOMAIN}"

    # assert returned field
    res = r.json
    assert "id" in res
    assert "email" in res
    assert "creation_date" in res
    assert "creation_timestamp" in res
    assert "nb_forward" in res
    assert "nb_block" in res
    assert "nb_reply" in res
    assert "enabled" in res
    assert "note" in res
    assert res["name"] == "your name"

    new_alias: Alias = Alias.get_by(email=r.json["alias"])
    assert new_alias.note == "test note"
    assert len(new_alias.mailboxes) == 2
