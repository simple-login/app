import arrow
import pytest
from flask import url_for

from app.db import Session
from app.models import Client, ClientUser, OauthToken
from tests.utils import create_new_user, random_string

# the same view is served under several paths
ROUTES = ["/oauth/user_info", "/oauth/me", "/oauth/userinfo"]


def create_oauth_token(expired: bool) -> OauthToken:
    user = create_new_user()
    client = Client.create_new(random_string(), user.id)
    Session.commit()
    # the authorize flow creates it before any token is issued
    ClientUser.create(client_id=client.id, user_id=user.id, commit=True)
    if expired:
        expiration = arrow.now().shift(hours=-1)
    else:
        expiration = arrow.now().shift(hours=1)
    return OauthToken.create(
        client_id=client.id,
        user_id=user.id,
        scope="email name",
        redirect_uri="https://example.com/callback",
        access_token=random_string(40),
        expired=expiration,
        commit=True,
    )


def test_user_info_with_valid_token_in_header(flask_client):
    token = create_oauth_token(expired=False)

    r = flask_client.get(
        url_for("oauth.user_info"),
        headers={"AUTHORIZATION": f"Bearer {token.access_token}"},
    )

    assert r.status_code == 200
    assert r.json["email"] == token.user.email


def test_user_info_with_valid_token_in_query_string(flask_client):
    token = create_oauth_token(expired=False)

    r = flask_client.get(
        url_for("oauth.user_info"), query_string={"access_token": token.access_token}
    )

    assert r.status_code == 200
    assert r.json["email"] == token.user.email


def test_user_info_with_expired_token_in_header(flask_client):
    token = create_oauth_token(expired=True)
    token_id = token.id

    r = flask_client.get(
        url_for("oauth.user_info"),
        headers={"AUTHORIZATION": f"Bearer {token.access_token}"},
    )

    assert r.status_code == 400
    assert r.json["error"] == "Expired access token"
    assert OauthToken.get(token_id) is None


def test_user_info_with_expired_token_in_query_string(flask_client):
    """An expired token has to be rejected however it was sent, the query
    string path used to skip the expiration check"""
    token = create_oauth_token(expired=True)
    token_id = token.id

    r = flask_client.get(
        url_for("oauth.user_info"), query_string={"access_token": token.access_token}
    )

    assert r.status_code == 400
    assert r.json["error"] == "Expired access token"
    assert OauthToken.get(token_id) is None


@pytest.mark.parametrize("route", ROUTES)
def test_user_info_expired_token_rejected_on_every_route(flask_client, route):
    token = create_oauth_token(expired=True)

    r = flask_client.get(route, query_string={"access_token": token.access_token})

    assert r.status_code == 400


def test_user_info_without_token(flask_client):
    r = flask_client.get(url_for("oauth.user_info"))

    assert r.status_code == 400
    assert r.json["error"] == "Invalid access token"


def test_user_info_with_unknown_token(flask_client):
    r = flask_client.get(
        url_for("oauth.user_info"), query_string={"access_token": random_string(40)}
    )

    assert r.status_code == 400
    assert r.json["error"] == "Invalid access token"
