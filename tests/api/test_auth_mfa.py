import pyotp
from flask import url_for
from itsdangerous import Signer

from app.config import FLASK_SECRET
from tests.utils import create_new_user


def test_auth_mfa_success(flask_client):
    user = create_new_user()
    user.enable_otp = True
    user.otp_secret = "base32secret3232"

    totp = pyotp.TOTP(user.otp_secret)
    s = Signer(FLASK_SECRET)
    mfa_key = s.sign(str(user.id))

    r = flask_client.post(
        url_for("api.auth_mfa"),
        json={"mfa_token": totp.now(), "mfa_key": mfa_key, "device": "Test Device"},
    )

    assert r.status_code == 200
    assert r.json["api_key"]
    assert r.json["email"]
    assert r.json["name"] == "Test User"


def test_auth_wrong_mfa_key(flask_client):
    user = create_new_user()
    user.enable_otp = True
    user.otp_secret = "base32secret3232"

    totp = pyotp.TOTP(user.otp_secret)

    r = flask_client.post(
        url_for("api.auth_mfa"),
        json={
            "mfa_token": totp.now(),
            "mfa_key": "wrong mfa key",
            "device": "Test Device",
        },
    )

    assert r.status_code == 400
    assert r.json["error"]
