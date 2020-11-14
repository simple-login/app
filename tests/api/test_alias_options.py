import json

from flask import url_for

from app.extensions import db
from app.models import User, ApiKey, AliasUsedOn, Alias


def test_different_scenarios(flask_client):
    user = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    # <<< without hostname >>>
    r = flask_client.get(
        url_for("api.options"), headers={"Authentication": api_key.code}
    )

    # {
    #     "can_create_custom": True,
    #     "custom": {"suffixes": ["azdwbw@sl.local"], "suggestion": ""},
    #     "existing": ["cat_cat_cat@sl.local"],
    # }
    assert r.status_code == 200
    assert r.json["can_create_custom"]
    assert len(r.json["existing"]) == 1
    assert len(r.json["custom"]["suffixes"]) == 4

    assert r.json["custom"]["suggestion"] == ""  # no hostname => no suggestion

    # <<< with hostname >>>
    r = flask_client.get(
        url_for("api.options", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
    )

    assert r.json["custom"]["suggestion"] == "test"

    # <<< with recommendation >>>
    alias = Alias.create_new(user, prefix="test")
    db.session.commit()
    AliasUsedOn.create(alias_id=alias.id, hostname="www.test.com", user_id=user.id)
    db.session.commit()

    r = flask_client.get(
        url_for("api.options", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
    )
    assert r.json["recommendation"]["alias"] == alias.email
    assert r.json["recommendation"]["hostname"] == "www.test.com"


def test_different_scenarios_v2(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    # <<< without hostname >>>
    r = flask_client.get(
        url_for("api.options_v2"), headers={"Authentication": api_key.code}
    )

    assert r.status_code == 200
    # {'can_create': True, 'existing': ['my-first-alias.chat@sl.local'], 'prefix_suggestion': '', 'suffixes': ['.meo@sl.local']}

    assert r.json["can_create"]
    assert len(r.json["existing"]) == 1
    assert r.json["suffixes"]
    assert r.json["prefix_suggestion"] == ""  # no hostname => no suggestion

    # <<< with hostname >>>
    r = flask_client.get(
        url_for("api.options_v2", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
    )

    assert r.json["prefix_suggestion"] == "test"

    # <<< with recommendation >>>
    alias = Alias.create_new(user, prefix="test")
    db.session.commit()
    AliasUsedOn.create(
        alias_id=alias.id, hostname="www.test.com", user_id=alias.user_id
    )
    db.session.commit()

    r = flask_client.get(
        url_for("api.options_v2", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
    )
    assert r.json["recommendation"]["alias"] == alias.email
    assert r.json["recommendation"]["hostname"] == "www.test.com"


def test_different_scenarios_v3(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    # <<< without hostname >>>
    r = flask_client.get(
        url_for("api.options_v3"), headers={"Authentication": api_key.code}
    )

    assert r.status_code == 200

    assert r.json["can_create"]
    assert r.json["suffixes"]
    assert r.json["prefix_suggestion"] == ""  # no hostname => no suggestion

    # <<< with hostname >>>
    r = flask_client.get(
        url_for("api.options_v3", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
    )

    assert r.json["prefix_suggestion"] == "test"

    # <<< with recommendation >>>
    alias = Alias.create_new(user, prefix="test")
    db.session.commit()
    AliasUsedOn.create(
        alias_id=alias.id, hostname="www.test.com", user_id=alias.user_id
    )
    db.session.commit()

    r = flask_client.get(
        url_for("api.options_v3", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
    )
    assert r.json["recommendation"]["alias"] == alias.email
    assert r.json["recommendation"]["hostname"] == "www.test.com"


def test_different_scenarios_v4(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

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
    db.session.commit()
    AliasUsedOn.create(
        alias_id=alias.id, hostname="www.test.com", user_id=alias.user_id
    )
    db.session.commit()

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
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

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
    print(json.dumps(r.json, indent=2))

    assert r.json["prefix_suggestion"] == "test"

    # <<< with recommendation >>>
    alias = Alias.create_new(user, prefix="test")
    db.session.commit()
    AliasUsedOn.create(
        alias_id=alias.id, hostname="www.test.com", user_id=alias.user_id
    )
    db.session.commit()

    r = flask_client.get(
        url_for("api.options_v4", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
    )
    assert r.json["recommendation"]["alias"] == alias.email
    assert r.json["recommendation"]["hostname"] == "www.test.com"
