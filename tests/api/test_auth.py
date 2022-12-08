import pytest
import unicodedata
from flask import url_for

from app.db import Session
from app.models import User, AccountActivation

PASSWORD_1 = "Aurélie"
PASSWORD_2 = unicodedata.normalize("NFKD", PASSWORD_1)
assert PASSWORD_1 != PASSWORD_2


@pytest.mark.parametrize("mfa", (True, False), ids=("MFA", "no MFA"))
def test_auth_login_success(flask_client, mfa: bool):
    User.create(
        email="abcd@gmail.com",
        password=PASSWORD_1,
        name="Test User",
        activated=True,
        enable_otp=mfa,
    )
    Session.commit()

    r = flask_client.post(
        "/api/auth/login",
        json={
            "email": "abcd@gmail.com",
            "password": PASSWORD_2,
            "device": "Test Device",
        },
    )

    assert r.status_code == 200
    assert r.json["name"] == "Test User"
    assert r.json["email"]

    if mfa:
        assert r.json["api_key"] is None
        assert r.json["mfa_enabled"]
        assert r.json["mfa_key"]
    else:
        assert r.json["api_key"]
        assert not r.json["mfa_enabled"]
        assert r.json["mfa_key"] is None


def test_auth_login_device_exist(flask_client):
    User.create(
        email="abcd@gmail.com", password="password", name="Test User", activated=True
    )
    Session.commit()

    r = flask_client.post(
        url_for("api.auth_login"),
        json={
            "email": "abcd@gmail.com",
            "password": "password",
            "device": "Test Device",
        },
    )

    assert r.status_code == 200
    api_key = r.json["api_key"]
    assert not r.json["mfa_enabled"]
    assert r.json["mfa_key"] is None
    assert r.json["name"] == "Test User"

    # same device, should return same api_key
    r = flask_client.post(
        url_for("api.auth_login"),
        json={
            "email": "abcd@gmail.com",
            "password": "password",
            "device": "Test Device",
        },
    )
    assert r.json["api_key"] == api_key


def test_auth_register_success(flask_client):
    assert AccountActivation.first() is None

    r = flask_client.post(
        url_for("api.auth_register"),
        json={"email": "abcd@gmail.com", "password": "password"},
    )

    assert r.status_code == 200
    assert r.json["msg"]

    # make sure an activation code is created
    act_code = AccountActivation.first()
    assert act_code
    assert len(act_code.code) == 6
    assert act_code.tries == 3


def test_auth_register_too_short_password(flask_client):
    r = flask_client.post(
        url_for("api.auth_register"),
        json={"email": "abcd@gmail.com", "password": "short"},
    )

    assert r.status_code == 400
    assert r.json["error"] == "password too short"


def test_auth_register_too_long_password(flask_client):
    r = flask_client.post(
        url_for("api.auth_register"),
        json={"email": "abcd@gmail.com", "password": "0123456789" * 11},
    )

    assert r.status_code == 400
    assert r.json["error"] == "password too long"


def test_auth_activate_success(flask_client):
    r = flask_client.post(
        url_for("api.auth_register"),
        json={"email": "abcd@gmail.com", "password": "password"},
    )

    assert r.status_code == 200
    assert r.json["msg"]

    # get the activation code
    act_code = AccountActivation.first()
    assert act_code
    assert len(act_code.code) == 6

    r = flask_client.post(
        url_for("api.auth_activate"),
        json={"email": "abcd@gmail.com", "code": act_code.code},
    )
    assert r.status_code == 200


def test_auth_activate_wrong_email(flask_client):
    r = flask_client.post(
        url_for("api.auth_activate"), json={"email": "abcd@gmail.com", "code": "123456"}
    )
    assert r.status_code == 400


def test_auth_activate_user_already_activated(flask_client):
    User.create(
        email="abcd@gmail.com", password="password", name="Test User", activated=True
    )
    Session.commit()

    r = flask_client.post(
        url_for("api.auth_activate"), json={"email": "abcd@gmail.com", "code": "123456"}
    )
    assert r.status_code == 400


def test_auth_activate_wrong_code(flask_client):
    r = flask_client.post(
        url_for("api.auth_register"),
        json={"email": "abcd@gmail.com", "password": "password"},
    )

    assert r.status_code == 200
    assert r.json["msg"]

    # get the activation code
    act_code = AccountActivation.first()
    assert act_code
    assert len(act_code.code) == 6
    assert act_code.tries == 3

    # make sure to create a wrong code
    wrong_code = act_code.code + "123"

    r = flask_client.post(
        url_for("api.auth_activate"),
        json={"email": "abcd@gmail.com", "code": wrong_code},
    )
    assert r.status_code == 400

    # make sure the nb tries decrements
    act_code = AccountActivation.first()
    assert act_code.tries == 2


def test_auth_activate_too_many_wrong_code(flask_client):
    r = flask_client.post(
        url_for("api.auth_register"),
        json={"email": "abcd@gmail.com", "password": "password"},
    )

    assert r.status_code == 200
    assert r.json["msg"]

    # get the activation code
    act_code = AccountActivation.first()
    assert act_code
    assert len(act_code.code) == 6
    assert act_code.tries == 3

    # make sure to create a wrong code
    wrong_code = act_code.code + "123"

    for _ in range(2):
        r = flask_client.post(
            url_for("api.auth_activate"),
            json={"email": "abcd@gmail.com", "code": wrong_code},
        )
        assert r.status_code == 400

    # the activation code is deleted
    r = flask_client.post(
        url_for("api.auth_activate"),
        json={"email": "abcd@gmail.com", "code": wrong_code},
    )

    assert r.status_code == 410

    # make sure the nb tries decrements
    assert AccountActivation.first() is None


def test_auth_reactivate_success(flask_client):
    User.create(email="abcd@gmail.com", password="password", name="Test User")
    Session.commit()

    r = flask_client.post(
        url_for("api.auth_reactivate"), json={"email": "abcd@gmail.com"}
    )
    assert r.status_code == 200

    # make sure an activation code is created
    act_code = AccountActivation.first()
    assert act_code
    assert len(act_code.code) == 6
    assert act_code.tries == 3


def test_auth_login_forgot_password(flask_client):
    User.create(
        email="abcd@gmail.com", password="password", name="Test User", activated=True
    )
    Session.commit()

    r = flask_client.post(
        url_for("api.forgot_password"),
        json={"email": "abcd@gmail.com"},
    )

    assert r.status_code == 200

    # No such email, still return 200
    r = flask_client.post(
        url_for("api.forgot_password"),
        json={"email": "not-exist@b.c"},
    )

    assert r.status_code == 200
