from flask import url_for

from app.db import Session
from app.models import User, ResetPasswordCode, MfaBrowser
from tests.utils import create_new_user, random_token


def test_successful_reset_password(flask_client):
    user = create_new_user()
    original_pass_hash = user.password
    user_id = user.id
    reset_code = random_token()
    ResetPasswordCode.create(user_id=user.id, code=reset_code)
    ResetPasswordCode.create(user_id=user.id, code=random_token())
    Session.commit()

    r = flask_client.post(
        url_for("auth.reset_password", code=reset_code),
        data={"password": "1231idsfjaads"},
    )

    assert r.status_code == 302

    assert ResetPasswordCode.get_by(user_id=user_id) is None
    user = User.get(user_id)
    assert user.password != original_pass_hash


def test_password_reset_invalidates_sessions_and_mfa(flask_client):
    user = create_new_user()
    source_alternative_id = random_token()
    user.alternative_id = source_alternative_id
    user.enable_otp = True
    user.otp_secret = "base32secret3232"

    original_pass_hash = user.password
    user_id = user.id

    # Create an MfaBrowser entry simulating a previously trusted device
    mfa_browser = MfaBrowser.create_new(user=user)
    Session.commit()

    # Verify the MfaBrowser entry exists
    assert MfaBrowser.get_by(token=mfa_browser.token) is not None

    # Generate a reset code
    reset_code = random_token()
    ResetPasswordCode.create(user_id=user.id, code=reset_code)
    Session.commit()

    # Perform password reset
    r = flask_client.post(
        url_for("auth.reset_password", code=reset_code),
        data={"password": "new_secure_password_123"},
    )

    assert r.status_code == 302

    # Reload user from database
    user = User.get(user_id)
    assert user.password != original_pass_hash
    assert MfaBrowser.get_by(token=mfa_browser.token) is None
    assert MfaBrowser.filter_by(user_id=user_id).count() == 0
    assert user.alternative_id != source_alternative_id
