from flask import url_for

from app.config import EMAIL_DOMAIN, MAX_NB_EMAIL_FREE_PLAN
from app.extensions import db
from app.models import User, ApiKey, Alias
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
