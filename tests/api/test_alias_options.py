from flask import url_for

from app.db import Session
from app.models import User, ApiKey, AliasUsedOn, Alias


def test_different_scenarios_v4(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    Session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    Session.commit()

    # <<< without hostname >>>
    r = flask_client.get(
        "/api/v4/alias/options", headers={"Authentication": api_key.code}
    )

    assert r.status_code == 200

    assert r.json["can_create"]
    assert r.json["suffixes"]
    assert r.json["prefix_suggestion"] == ""  # no hostname => no suggestion

    # <<< with hostname >>>
    r = flask_client.get(
        url_for("api.options_v4", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
    )

    assert r.json["prefix_suggestion"] == "test"

    # <<< with recommendation >>>
    alias = Alias.create_new(user, prefix="test")
    Session.commit()
    AliasUsedOn.create(
        alias_id=alias.id, hostname="www.test.com", user_id=alias.user_id
    )
    Session.commit()

    r = flask_client.get(
        url_for("api.options_v4", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
    )
    assert r.json["recommendation"]["alias"] == alias.email
    assert r.json["recommendation"]["hostname"] == "www.test.com"


def test_different_scenarios_v4_2(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    Session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    Session.commit()

    # <<< without hostname >>>
    r = flask_client.get(
        url_for("api.options_v4"), headers={"Authentication": api_key.code}
    )

    assert r.status_code == 200

    assert r.json["can_create"]
    assert r.json["suffixes"]
    assert r.json["prefix_suggestion"] == ""  # no hostname => no suggestion

    for (suffix, signed_suffix) in r.json["suffixes"]:
        assert signed_suffix.startswith(suffix)

    # <<< with hostname >>>
    r = flask_client.get(
        url_for("api.options_v4", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
    )

    assert r.json["prefix_suggestion"] == "test"

    # <<< with recommendation >>>
    alias = Alias.create_new(user, prefix="test")
    Session.commit()
    AliasUsedOn.create(
        alias_id=alias.id, hostname="www.test.com", user_id=alias.user_id
    )
    Session.commit()

    r = flask_client.get(
        url_for("api.options_v4", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
    )
    assert r.json["recommendation"]["alias"] == alias.email
    assert r.json["recommendation"]["hostname"] == "www.test.com"


def test_different_scenarios_v5(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    Session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    Session.commit()

    # <<< without hostname >>>
    r = flask_client.get(
        "/api/v5/alias/options", headers={"Authentication": api_key.code}
    )

    assert r.status_code == 200

    assert r.json["can_create"]
    assert r.json["suffixes"]
    assert r.json["prefix_suggestion"] == ""  # no hostname => no suggestion

    for suffix_payload in r.json["suffixes"]:
        suffix, signed_suffix = (
            suffix_payload["suffix"],
            suffix_payload["signed_suffix"],
        )
        assert signed_suffix.startswith(suffix)

    # <<< with hostname >>>
    r = flask_client.get(
        "/api/v5/alias/options?hostname=www.test.com",
        headers={"Authentication": api_key.code},
    )
    assert r.json["prefix_suggestion"] == "test"

    # <<< with hostname with 2 parts TLD, for example wwww.numberoneshoes.co.nz >>>
    r = flask_client.get(
        "/api/v5/alias/options?hostname=wwww.numberoneshoes.co.nz",
        headers={"Authentication": api_key.code},
    )
    assert r.json["prefix_suggestion"] == "numberoneshoes"

    # <<< with recommendation >>>
    alias = Alias.create_new(user, prefix="test")
    Session.commit()
    AliasUsedOn.create(
        alias_id=alias.id, hostname="www.test.com", user_id=alias.user_id
    )
    Session.commit()

    r = flask_client.get(
        url_for("api.options_v4", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
    )
    assert r.json["recommendation"]["alias"] == alias.email
    assert r.json["recommendation"]["hostname"] == "www.test.com"
