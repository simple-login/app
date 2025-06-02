from flask import url_for
from urllib.parse import parse_qs
from urllib3.util import parse_url

from app.config import URL, PROTON_CLIENT_ID


def test_login_with_proton(flask_client):
    r = flask_client.get(
        url_for("auth.proton_login"),
        follow_redirects=False,
    )
    location = r.headers.get("Location")
    assert location is not None

    parsed = parse_url(location)
    query = parse_qs(parsed.query)

    expected_redirect_url = f"{URL}/auth/proton/callback"

    assert "code" == query["response_type"][0]
    assert PROTON_CLIENT_ID == query["client_id"][0]
    assert expected_redirect_url == query["redirect_uri"][0]
