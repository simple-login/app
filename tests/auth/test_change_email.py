from flask import url_for

from app.db import Session
from app.models import EmailChange, User, ResetPasswordCode
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
