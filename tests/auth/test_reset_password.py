from flask import url_for

from app.db import Session
from app.models import User, ResetPasswordCode
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
