from app import config
from flask import url_for, session
from urllib.parse import parse_qs
from urllib3.util import parse_url
from app.auth.views.oidc import create_user
from app.utils import random_string
from unittest.mock import patch
from app.models import User

from app.config import URL, OIDC_CLIENT_ID


mock_well_known_response = {
    "authorization_endpoint": "http://localhost:7777/authorization-endpoint",
    "userinfo_endpoint": "http://localhost:7777/userinfo-endpoint",
    "token_endpoint": "http://localhost:7777/token-endpoint",
}


@patch("requests.get")
def test_oidc_login(mock_get, flask_client):
    config.OIDC_WELL_KNOWN_URL = "http://localhost:7777/well-known-url"
    with flask_client.session_transaction() as sess:
        sess["oauth_redirect_next"] = None

    mock_get.return_value.json.return_value = mock_well_known_response

    r = flask_client.get(
        url_for("auth.oidc_login"),
        follow_redirects=False,
    )
    location = r.headers.get("Location")
    assert location is not None

    parsed = parse_url(location)
    query = parse_qs(parsed.query)

    expected_redirect_url = f"{URL}/auth/oidc/callback"

    assert "code" == query["response_type"][0]
    assert OIDC_CLIENT_ID == query["client_id"][0]
    assert expected_redirect_url == query["redirect_uri"][0]


@patch("requests.get")
def test_oidc_login_next_url(mock_get, flask_client):
    config.OIDC_WELL_KNOWN_URL = "http://localhost:7777/well-known-url"
    with flask_client.session_transaction() as sess:
        sess["oauth_redirect_next"] = None

    mock_get.return_value.json.return_value = mock_well_known_response

    with flask_client:
        r = flask_client.get(
            url_for("auth.oidc_login", next="/dashboard/settings/"),
            follow_redirects=False,
        )
        location = r.headers.get("Location")
        assert location is not None

        parsed = parse_url(location)
        query = parse_qs(parsed.query)

        expected_redirect_url = f"{URL}/auth/oidc/callback"

        assert "code" == query["response_type"][0]
        assert OIDC_CLIENT_ID == query["client_id"][0]
        assert expected_redirect_url == query["redirect_uri"][0]
        assert session["oauth_redirect_next"] == "/dashboard/settings/"


@patch("requests.get")
def test_oidc_login_no_client_id(mock_get, flask_client):
    config.OIDC_CLIENT_ID = None
    config.OIDC_WELL_KNOWN_URL = "http://localhost:7777/well-known-url"
    with flask_client.session_transaction() as sess:
        sess["oauth_redirect_next"] = None

    mock_get.return_value.json.return_value = mock_well_known_response

    r = flask_client.get(
        url_for("auth.oidc_login"),
        follow_redirects=False,
    )
    location = r.headers.get("Location")
    assert location is not None

    parsed = parse_url(location)

    expected_redirect_url = "/auth/login"

    assert expected_redirect_url == parsed.path

    config.OIDC_CLIENT_ID = "to_fill"


@patch("requests.get")
def test_oidc_login_no_client_secret(mock_get, flask_client):
    config.OIDC_CLIENT_SECRET = None
    config.OIDC_WELL_KNOWN_URL = "http://localhost:7777/well-known-url"
    with flask_client.session_transaction() as sess:
        sess["oauth_redirect_next"] = None

    mock_get.return_value.json.return_value = mock_well_known_response

    r = flask_client.get(
        url_for("auth.oidc_login"),
        follow_redirects=False,
    )
    location = r.headers.get("Location")
    assert location is not None

    parsed = parse_url(location)

    expected_redirect_url = "/auth/login"

    assert expected_redirect_url == parsed.path

    config.OIDC_CLIENT_SECRET = "to_fill"


@patch("requests.get")
def test_oidc_callback_no_oauth_state(mock_get, flask_client):
    config.OIDC_WELL_KNOWN_URL = "http://localhost:7777/well-known-url"
    with flask_client.session_transaction() as sess:
        sess["oauth_redirect_next"] = None
        sess["oauth_state"] = None

    mock_get.return_value.json.return_value = mock_well_known_response

    r = flask_client.get(
        url_for("auth.oidc_callback"),
        follow_redirects=False,
    )
    location = r.headers.get("Location")
    assert location is None


@patch("requests.get")
def test_oidc_callback_no_client_id(mock_get, flask_client):
    config.OIDC_WELL_KNOWN_URL = "http://localhost:7777/well-known-url"
    with flask_client.session_transaction() as sess:
        sess["oauth_redirect_next"] = None
        sess["oauth_state"] = "state"
    config.OIDC_CLIENT_ID = None

    mock_get.return_value.json.return_value = mock_well_known_response

    r = flask_client.get(
        url_for("auth.oidc_callback"),
        follow_redirects=False,
    )
    location = r.headers.get("Location")
    assert location is not None

    parsed = parse_url(location)

    expected_redirect_url = "/auth/login"

    assert expected_redirect_url == parsed.path

    config.OIDC_CLIENT_ID = "to_fill"
    with flask_client.session_transaction() as sess:
        sess["oauth_state"] = None


@patch("requests.get")
def test_oidc_callback_no_client_secret(mock_get, flask_client):
    config.OIDC_WELL_KNOWN_URL = "http://localhost:7777/well-known-url"
    with flask_client.session_transaction() as sess:
        sess["oauth_redirect_next"] = None
        sess["oauth_state"] = "state"
    config.OIDC_CLIENT_SECRET = None

    mock_get.return_value.json.return_value = mock_well_known_response

    r = flask_client.get(
        url_for("auth.oidc_callback"),
        follow_redirects=False,
    )
    location = r.headers.get("Location")
    assert location is not None

    parsed = parse_url(location)

    expected_redirect_url = "/auth/login"

    assert expected_redirect_url == parsed.path

    config.OIDC_CLIENT_SECRET = "to_fill"
    with flask_client.session_transaction() as sess:
        sess["oauth_state"] = None


@patch("requests.get")
@patch("requests_oauthlib.OAuth2Session.fetch_token")
@patch("requests_oauthlib.OAuth2Session.get")
def test_oidc_callback_invalid_user(
    mock_oauth_get, mock_fetch_token, mock_get, flask_client
):
    mock_oauth_get.return_value = MockResponse(400, {})
    config.OIDC_WELL_KNOWN_URL = "http://localhost:7777/well-known-url"
    with flask_client.session_transaction() as sess:
        sess["oauth_redirect_next"] = None
        sess["oauth_state"] = "state"

    mock_get.return_value.json.return_value = mock_well_known_response

    r = flask_client.get(
        url_for("auth.oidc_callback"),
        follow_redirects=False,
    )
    location = r.headers.get("Location")
    assert location is not None

    parsed = parse_url(location)

    expected_redirect_url = "/auth/login"

    assert expected_redirect_url == parsed.path
    assert mock_oauth_get.called

    with flask_client.session_transaction() as sess:
        sess["oauth_state"] = None


@patch("requests.get")
@patch("requests_oauthlib.OAuth2Session.fetch_token")
@patch("requests_oauthlib.OAuth2Session.get")
def test_oidc_callback_no_email(
    mock_oauth_get, mock_fetch_token, mock_get, flask_client
):
    mock_oauth_get.return_value = MockResponse(200, {})
    config.OIDC_WELL_KNOWN_URL = "http://localhost:7777/well-known-url"
    with flask_client.session_transaction() as sess:
        sess["oauth_redirect_next"] = None
        sess["oauth_state"] = "state"

    mock_get.return_value.json.return_value = mock_well_known_response

    r = flask_client.get(
        url_for("auth.oidc_callback"),
        follow_redirects=False,
    )
    location = r.headers.get("Location")
    assert location is not None

    parsed = parse_url(location)

    expected_redirect_url = "/auth/login"

    assert expected_redirect_url == parsed.path
    assert mock_oauth_get.called

    with flask_client.session_transaction() as session:
        session["oauth_state"] = None


@patch("requests.get")
@patch("requests_oauthlib.OAuth2Session.fetch_token")
@patch("requests_oauthlib.OAuth2Session.get")
def test_oidc_callback_disabled_registration(
    mock_oauth_get, mock_fetch_token, mock_get, flask_client
):
    config.DISABLE_REGISTRATION = True
    email = random_string()
    mock_oauth_get.return_value = MockResponse(200, {"email": email})
    config.OIDC_WELL_KNOWN_URL = "http://localhost:7777/well-known-url"
    with flask_client.session_transaction() as sess:
        sess["oauth_redirect_next"] = None
        sess["oauth_state"] = "state"

    mock_get.return_value.json.return_value = mock_well_known_response

    r = flask_client.get(
        url_for("auth.oidc_callback"),
        follow_redirects=False,
    )
    location = r.headers.get("Location")
    assert location is not None

    parsed = parse_url(location)

    expected_redirect_url = "/auth/register"

    assert expected_redirect_url == parsed.path
    assert mock_oauth_get.called

    config.DISABLE_REGISTRATION = False
    with flask_client.session_transaction() as sess:
        sess["oauth_state"] = None


@patch("requests.get")
@patch("requests_oauthlib.OAuth2Session.fetch_token")
@patch("requests_oauthlib.OAuth2Session.get")
def test_oidc_callback_registration(
    mock_oauth_get, mock_fetch_token, mock_get, flask_client
):
    email = random_string()
    mock_oauth_get.return_value = MockResponse(
        200,
        {
            "email": email,
            config.OIDC_NAME_FIELD: "name",
        },
    )
    config.OIDC_WELL_KNOWN_URL = "http://localhost:7777/well-known-url"
    with flask_client.session_transaction() as sess:
        sess["oauth_redirect_next"] = None
        sess["oauth_state"] = "state"

    mock_get.return_value.json.return_value = mock_well_known_response

    user = User.get_by(email=email)
    assert user is None

    r = flask_client.get(
        url_for("auth.oidc_callback"),
        follow_redirects=False,
    )
    location = r.headers.get("Location")
    assert location is not None

    parsed = parse_url(location)

    expected_redirect_url = "/dashboard/"

    assert expected_redirect_url == parsed.path
    assert mock_oauth_get.called

    user = User.get_by(email=email)
    assert user is not None
    assert user.email == email

    with flask_client.session_transaction() as sess:
        sess["oauth_state"] = None


@patch("requests.get")
@patch("requests_oauthlib.OAuth2Session.fetch_token")
@patch("requests_oauthlib.OAuth2Session.get")
def test_oidc_callback_login(mock_oauth_get, mock_fetch_token, mock_get, flask_client):
    email = random_string()
    mock_oauth_get.return_value = MockResponse(
        200,
        {
            "email": email,
        },
    )
    config.OIDC_WELL_KNOWN_URL = "http://localhost:7777/well-known-url"
    with flask_client.session_transaction() as sess:
        sess["oauth_redirect_next"] = None
        sess["oauth_state"] = "state"

    mock_get.return_value.json.return_value = mock_well_known_response

    user = User.create(
        email=email,
        name="name",
        password="",
        activated=True,
    )
    user = User.get_by(email=email)
    assert user is not None

    r = flask_client.get(
        url_for("auth.oidc_callback"),
        follow_redirects=False,
    )
    location = r.headers.get("Location")
    assert location is not None

    parsed = parse_url(location)

    expected_redirect_url = "/dashboard/"

    assert expected_redirect_url == parsed.path
    assert mock_oauth_get.called

    with flask_client.session_transaction() as sess:
        sess["oauth_state"] = None


@patch("requests.get")
@patch("requests_oauthlib.OAuth2Session.fetch_token")
@patch("requests_oauthlib.OAuth2Session.get")
def test_oidc_callback_login_with_next_url(
    mock_oauth_get, mock_fetch_token, mock_get, flask_client
):
    email = random_string()
    mock_oauth_get.return_value = MockResponse(
        200,
        {
            "email": email,
        },
    )
    config.OIDC_WELL_KNOWN_URL = "http://localhost:7777/well-known-url"
    with flask_client.session_transaction() as sess:
        sess["oauth_redirect_next"] = "/dashboard/settings/"
        sess["oauth_state"] = "state"

    mock_get.return_value.json.return_value = mock_well_known_response

    user = User.create(
        email=email,
        name="name",
        password="",
        activated=True,
    )
    user = User.get_by(email=email)
    assert user is not None

    r = flask_client.get(
        url_for("auth.oidc_callback"),
        follow_redirects=False,
    )
    location = r.headers.get("Location")
    assert location is not None

    parsed = parse_url(location)

    expected_redirect_url = "/dashboard/settings/"

    assert expected_redirect_url == parsed.path
    assert mock_oauth_get.called

    with flask_client.session_transaction() as sess:
        sess["oauth_state"] = None


def test_create_user():
    email = random_string()
    user = create_user(
        email,
        {
            config.OIDC_NAME_FIELD: "name",
        },
    )
    assert user.email == email
    assert user.name == "name"
    assert user.activated


class MockResponse:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self.json_data = json_data
        self.text = "error"

    def json(self):
        return self.json_data
