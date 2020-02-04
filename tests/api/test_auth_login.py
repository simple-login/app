from flask import url_for

from app.extensions import db
from app.models import User


def test_auth_login_success_mfa_disabled(flask_client):
    User.create(email="a@b.c", password="password", name="Test User", activated=True)
    db.session.commit()

    r = flask_client.post(
        url_for("api.auth_login"),
        json={"email": "a@b.c", "password": "password", "device": "Test Device"},
    )

    assert r.status_code == 200
    assert r.json["api_key"]
    assert r.json["mfa_enabled"] == False
    assert r.json["mfa_key"] is None
    assert r.json["name"] == "Test User"


def test_auth_login_success_mfa_enabled(flask_client):
    User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
        enable_otp=True,
    )
    db.session.commit()

    r = flask_client.post(
        url_for("api.auth_login"),
        json={"email": "a@b.c", "password": "password", "device": "Test Device"},
    )

    assert r.status_code == 200
    assert r.json["api_key"] is None
    assert r.json["mfa_enabled"] == True
    assert r.json["mfa_key"]
    assert r.json["name"] == "Test User"
