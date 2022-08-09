from random import random

from flask import url_for

from app.models import ApiToCookieToken
from tests.utils import create_new_user


def test_get_cookie(flask_client):
    user = create_new_user()
    token = ApiToCookieToken.create(
        user_id=user.id, code=f"random{random()}", commit=True
    )
    token_code = token.code
    token_id = token.id

    r = flask_client.post(
        url_for("auth.api_to_cookie", next=url_for("dashboard.setting")),
        json={"token": token_code},
        follow_redirects=True,
    )

    assert ApiToCookieToken.get(token_id) is None
    assert r.headers.getlist("Set-Cookie") is not None
