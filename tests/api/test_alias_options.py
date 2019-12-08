from flask import url_for

from app.extensions import db
from app.models import User, ApiKey, AliasUsedOn, GenEmail


def test_different_scenarios(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    # <<< without hostname >>>
    r = flask_client.get(
        url_for("api.options"), headers={"Authentication": api_key.code}
    )

    # {
    #     "can_create_custom": True,
    #     "can_create_random": True,
    #     "custom": {"suffixes": ["azdwbw@sl.local"], "suggestion": ""},
    #     "existing": ["cat_cat_cat@sl.local"],
    # }
    assert r.status_code == 200
    assert r.json["can_create_custom"]
    assert r.json["can_create_random"]
    assert len(r.json["existing"]) == 1
    assert r.json["custom"]["suffixes"]
    assert r.json["custom"]["suggestion"] == ""  # no hostname => no suggestion

    # <<< with hostname >>>
    r = flask_client.get(
        url_for("api.options", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
    )

    assert r.json["custom"]["suggestion"] == "test"

    # <<< with recommendation >>>
    alias = GenEmail.create_custom_alias(user.id, prefix="test")
    db.session.commit()
    AliasUsedOn.create(gen_email_id=alias.id, hostname="www.test.com")
    db.session.commit()

    r = flask_client.get(
        url_for("api.options", hostname="www.test.com"),
        headers={"Authentication": api_key.code},
    )
    assert r.json["recommendation"]["alias"] == alias.email
    assert r.json["recommendation"]["hostname"] == "www.test.com"
