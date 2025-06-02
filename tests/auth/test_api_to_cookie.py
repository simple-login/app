from flask import url_for

from app.models import ApiToCookieToken, ApiKey
from tests.utils import create_new_user, login


def test_get_cookie(flask_client):
    user = create_new_user()
    api_key = ApiKey.create(
        user_id=user.id,
        commit=True,
    )
    token = ApiToCookieToken.create(
        user_id=user.id,
        api_key_id=api_key.id,
        commit=True,
    )
    token_code = token.code
    token_id = token.id

    r = flask_client.get(
        url_for(
            "auth.api_to_cookie", token=token_code, next=url_for("dashboard.setting")
        ),
        follow_redirects=True,
    )

    assert ApiToCookieToken.get(token_id) is None
    assert r.headers.getlist("Set-Cookie") is not None


def test_get_cookie_does_not_allow_to_change_user(flask_client):
    user = create_new_user()
    api_key = ApiKey.create(
        user_id=user.id,
        commit=True,
    )
    token = ApiToCookieToken.create(
        user_id=user.id,
        api_key_id=api_key.id,
        commit=True,
    )
    token_code = token.code

    other_user = create_new_user()
    login(flask_client, other_user)

    r = flask_client.get(
        url_for(
            "auth.api_to_cookie", token=token_code, next=url_for("dashboard.setting")
        ),
        follow_redirects=False,
    )

    assert r.status_code == 302
    assert r.location.endswith("/auth/login")
