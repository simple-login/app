import uuid

from flask import url_for

from app.config import EMAIL_DOMAIN, MAX_NB_EMAIL_FREE_PLAN
from app.extensions import db
from app.models import User, ApiKey, Alias


def test_success(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    r = flask_client.post(
        url_for("api.new_random_alias", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
    )

    assert r.status_code == 201
    assert r.json["alias"].endswith(EMAIL_DOMAIN)

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


def test_custom_mode(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    # without note
    r = flask_client.post(
        url_for("api.new_random_alias", hostname="www.test.com", mode="uuid"),
        headers={"Authentication": api_key.code},
    )

    assert r.status_code == 201
    # extract the uuid part
    alias = r.json["alias"]
    uuid_part = alias[: len(alias) - len(EMAIL_DOMAIN) - 1]
    assert is_valid_uuid(uuid_part)

    # with note
    r = flask_client.post(
        url_for("api.new_random_alias", hostname="www.test.com", mode="uuid"),
        headers={"Authentication": api_key.code},
        json={"note": "test note"},
    )

    assert r.status_code == 201
    alias = r.json["alias"]
    ge = Alias.get_by(email=alias)
    assert ge.note == "test note"


def test_out_of_quota(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    user.trial_end = None
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    # create MAX_NB_EMAIL_FREE_PLAN random alias to run out of quota
    for _ in range(MAX_NB_EMAIL_FREE_PLAN):
        Alias.create_new(user, prefix="test1")

    r = flask_client.post(
        url_for("api.new_random_alias", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
    )

    assert r.status_code == 400
    assert (
        r.json["error"]
        == "You have reached the limitation of a free account with the maximum of 3 aliases, please upgrade your plan to create more aliases"
    )


def is_valid_uuid(val):
    try:
        uuid.UUID(str(val))
        return True
    except ValueError:
        return False
