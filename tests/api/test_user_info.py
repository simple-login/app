from flask import url_for

from app.extensions import db
from app.models import User, ApiKey


def test_user_in_trial(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    db.session.commit()

    r = flask_client.get(
        url_for("api.user_info"), headers={"Authentication": api_key.code}
    )

    assert r.status_code == 200
    assert r.json == {
        "is_premium": True,
        "name": "Test User",
        "email": "a@b.c",
        "in_trial": True,
    }


def test_wrong_api_key(flask_client):
    r = flask_client.get(
        url_for("api.user_info"), headers={"Authentication": "Invalid code"}
    )

    assert r.status_code == 401

    assert r.json == {"error": "Wrong api key"}
