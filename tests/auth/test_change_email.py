from flask import url_for

from app.db import Session
from app.models import EmailChange, User, ResetPasswordCode, ApiKey, MfaBrowser
from tests.utils import create_new_user, random_token, random_email


def test_change_email(flask_client):
    user = create_new_user()
    user.activated = False
    user_id = user.id
    email_change = EmailChange.create(
        user_id=user.id,
        code=random_token(),
        new_email=random_email(),
    )
    reset_id = ResetPasswordCode.create(user_id=user_id, code=random_token()).id
    email_change_id = email_change.id
    email_change_code = email_change.code
    new_email = email_change.new_email
    Session.commit()

    r = flask_client.get(
        url_for("auth.change_email", code=email_change_code),
        follow_redirects=True,
    )

    assert r.status_code == 200

    user = User.get(user_id)
    assert user.email == new_email
    assert EmailChange.get(email_change_id) is None
    assert ResetPasswordCode.get(reset_id) is None


def test_change_email_invalidates_sessions_and_tokens(flask_client):
    user = create_new_user()
    user_id = user.id
    source_alternative_id = random_token()
    user.alternative_id = source_alternative_id
    Session.commit()

    # Create API keys
    _api_key_1 = ApiKey.create(user_id=user_id, name="Test Key 1")
    _api_key_2 = ApiKey.create(user_id=user_id, name="Test Key 2")
    Session.commit()

    # Create MFA browser token
    mfa_browser = MfaBrowser.create_new(user=user)
    mfa_token = mfa_browser.token
    Session.commit()

    # Verify tokens exist
    assert ApiKey.filter_by(user_id=user_id).count() == 2
    assert MfaBrowser.get_by(token=mfa_token) is not None

    # Create email change
    email_change = EmailChange.create(
        user_id=user_id,
        code=random_token(),
        new_email=random_email(),
    )
    email_change_code = email_change.code
    Session.commit()

    # Complete email change
    r = flask_client.get(
        url_for("auth.change_email", code=email_change_code),
        follow_redirects=True,
    )

    assert r.status_code == 200

    # Verify all sessions and tokens have been invalidated
    assert ApiKey.filter_by(user_id=user_id).count() == 0
    assert MfaBrowser.get_by(token=mfa_token) is None
    user = User.get(user_id)
    assert user.alternative_id != source_alternative_id
