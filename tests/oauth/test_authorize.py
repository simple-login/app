import base64
import json
from urllib.parse import urlparse, parse_qs

from flask import url_for

from app.db import Session
from app.jose_utils import verify_id_token, decode_id_token
from app.models import Client, User, ClientUser, RedirectUri
from app.oauth.views.authorize import (
    get_host_name_and_scheme,
    generate_access_token,
    construct_url,
)
from tests.utils import login, random_domain, random_string, random_email


def generate_random_uri() -> str:
    return f"https://{random_domain()}/callback"


def test_get_host_name_and_scheme():
    assert get_host_name_and_scheme("http://localhost:8000?a=b") == (
        "localhost",
        "http",
    )

    assert get_host_name_and_scheme(
        "https://www.bubblecode.net/en/2016/01/22/understanding-oauth2/#Implicit_Grant"
    ) == ("www.bubblecode.net", "https")


def test_generate_access_token(flask_client):
    access_token = generate_access_token()
    assert len(access_token) == 40


def test_construct_url():
    url = construct_url("http://ab.cd", {"x": "1 2"})
    assert url == "http://ab.cd?x=1%202"


def test_authorize_page_non_login_user(flask_client):
    """make sure to display login page for non-authenticated user"""
    user = User.create(random_email(), random_string())
    Session.commit()

    client = Client.create_new(random_string(), user.id)
    Session.commit()

    uri = generate_random_uri()
    RedirectUri.create(
        client_id=client.id,
        uri=uri,
        commit=True,
    )

    r = flask_client.get(
        url_for(
            "oauth.authorize",
            client_id=client.oauth_client_id,
            state="teststate",
            redirect_uri=uri,
            response_type="code",
        )
    )

    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "Sign in to accept sharing data with" in html


def test_authorize_page_login_user_non_supported_flow(flask_client):
    """return 400 if the flow is not supported"""
    user = login(flask_client)
    client = Client.create_new("test client", user.id)
    Session.commit()

    # Not provide any flow
    r = flask_client.get(
        url_for(
            "oauth.authorize",
            client_id=client.oauth_client_id,
            state="teststate",
            redirect_uri="http://localhost",
            # not provide response_type param here
        )
    )

    # Provide a not supported flow
    html = r.get_data(as_text=True)
    assert r.status_code == 400
    assert "SimpleLogin only support the following OIDC flows" in html

    r = flask_client.get(
        url_for(
            "oauth.authorize",
            client_id=client.oauth_client_id,
            state="teststate",
            redirect_uri="http://localhost",
            # SL does not support this flow combination
            response_type="code token id_token",
        )
    )

    html = r.get_data(as_text=True)
    assert r.status_code == 400
    assert "SimpleLogin only support the following OIDC flows" in html


def test_authorize_page_login_user(flask_client):
    """make sure to display authorization page for authenticated user"""
    user = login(flask_client)
    client = Client.create_new("test client", user.id)

    Session.commit()

    uri = generate_random_uri()
    RedirectUri.create(
        client_id=client.id,
        uri=uri,
        commit=True,
    )

    r = flask_client.get(
        url_for(
            "oauth.authorize",
            client_id=client.oauth_client_id,
            state="teststate",
            redirect_uri=uri,
            response_type="code",
        )
    )

    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert f"{user.email} (Personal Email)" in html


def test_authorize_code_flow_no_openid_scope(flask_client):
    """make sure the authorize redirects user to correct page for the *Code Flow*
    and when the *openid* scope is not present
    , ie when response_type=code, openid not in scope
    """

    user = login(flask_client)
    client = Client.create_new("test client", user.id)
    Session.commit()
    domain = random_domain()
    uri = f"https://{domain}/callback"
    RedirectUri.create(
        client_id=client.id,
        uri=uri,
        commit=True,
    )

    # user allows client on the authorization page
    r = flask_client.post(
        url_for(
            "oauth.authorize",
            client_id=client.oauth_client_id,
            state="teststate",
            redirect_uri=uri,
            response_type="code",
        ),
        data={"button": "allow", "suggested-email": "x@y.z", "suggested-name": "AB CD"},
        # user will be redirected to client page, do not allow redirection here
        # to assert the redirect url
        # follow_redirects=True,
    )

    assert r.status_code == 302  # user gets redirected back to client page

    # r.location will have this form http://localhost?state=teststate&code=knuyjepwvg
    o = urlparse(r.location)
    assert o.netloc == domain
    assert not o.fragment

    # parse the query, should return something like
    # {'state': ['teststate'], 'code': ['knuyjepwvg']}
    queries = parse_qs(o.query)
    assert len(queries) == 2

    assert queries["state"] == ["teststate"]
    assert len(queries["code"]) == 1

    # Exchange the code to get access_token
    basic_auth_headers = base64.b64encode(
        f"{client.oauth_client_id}:{client.oauth_client_secret}".encode()
    ).decode("utf-8")

    r = flask_client.post(
        url_for("oauth.token"),
        headers={"Authorization": "Basic " + basic_auth_headers},
        data={"grant_type": "authorization_code", "code": queries["code"][0]},
    )

    # r.json should have this format
    # {
    #   'access_token': 'avmhluhonsouhcwwailydwvhankspptgidoggcbu',
    #   'expires_in': 3600,
    #   'scope': '',
    #   'token_type': 'bearer',
    #   'user': {
    #     'avatar_url': None,
    #     'client': 'test client',
    #     'email': 'x@y.z',
    #     'email_verified': True,
    #     'id': 1,
    #     'name': 'AB CD'
    #   }
    # }
    assert r.status_code == 200
    assert r.json["access_token"]
    assert r.json["expires_in"] == 3600
    assert not r.json["scope"]
    assert r.json["token_type"] == "Bearer"

    client_user = ClientUser.get_by(client_id=client.id)

    assert r.json["user"] == {
        "avatar_url": None,
        "client": "test client",
        "email": "x@y.z",
        "email_verified": True,
        "id": client_user.id,
        "name": "AB CD",
        "sub": str(client_user.id),
    }


def test_authorize_code_flow_with_openid_scope(flask_client):
    """make sure the authorize redirects user to correct page for the *Code Flow*
    and when the *openid* scope is present
    , ie when response_type=code, openid in scope

    The authorize endpoint should stay the same: return the *code*.
    The token endpoint however should now return id_token in addition to the access_token
    """

    user = login(flask_client)
    client = Client.create_new("test client", user.id)

    Session.commit()

    domain = random_domain()
    uri = f"https://{domain}/callback"
    RedirectUri.create(
        client_id=client.id,
        uri=uri,
        commit=True,
    )

    # user allows client on the authorization page
    r = flask_client.post(
        url_for(
            "oauth.authorize",
            client_id=client.oauth_client_id,
            state="teststate",
            redirect_uri=uri,
            response_type="code",
            scope="openid",  # openid is in scope
        ),
        data={"button": "allow", "suggested-email": "x@y.z", "suggested-name": "AB CD"},
        # user will be redirected to client page, do not allow redirection here
        # to assert the redirect url
        # follow_redirects=True,
    )

    assert r.status_code == 302  # user gets redirected back to client page

    # r.location will have this form http://localhost?state=teststate&code=knuyjepwvg
    o = urlparse(r.location)
    assert o.netloc == domain
    assert not o.fragment

    # parse the query, should return something like
    # {'state': ['teststate'], 'code': ['knuyjepwvg'], 'scope': ["openid"]}
    queries = parse_qs(o.query)
    assert len(queries) == 3

    assert queries["state"] == ["teststate"]
    assert len(queries["code"]) == 1

    # Exchange the code to get access_token
    basic_auth_headers = base64.b64encode(
        f"{client.oauth_client_id}:{client.oauth_client_secret}".encode()
    ).decode("utf-8")

    r = flask_client.post(
        url_for("oauth.token"),
        headers={"Authorization": "Basic " + basic_auth_headers},
        data={"grant_type": "authorization_code", "code": queries["code"][0]},
    )

    # r.json should have this format
    # {
    #   'access_token': 'avmhluhonsouhcwwailydwvhankspptgidoggcbu',
    #   'expires_in': 3600,
    #   'scope': '',
    #   'token_type': 'bearer',
    #   'user': {
    #     'avatar_url': None,
    #     'client': 'test client',
    #     'email': 'x@y.z',
    #     'email_verified': True,
    #     'id': 1,
    #     'name': 'AB CD'
    #   }
    # }
    assert r.status_code == 200
    assert r.json["access_token"]
    assert r.json["expires_in"] == 3600
    assert r.json["scope"] == "openid"
    assert r.json["token_type"] == "Bearer"

    client_user = ClientUser.get_by(client_id=client.id)

    assert r.json["user"] == {
        "avatar_url": None,
        "client": "test client",
        "email": "x@y.z",
        "email_verified": True,
        "id": client_user.id,
        "name": "AB CD",
        "sub": str(client_user.id),
    }

    # id_token must be returned
    assert r.json["id_token"]

    # id_token must be a valid, correctly signed JWT
    assert verify_id_token(r.json["id_token"])


def test_authorize_token_flow(flask_client):
    """make sure the authorize redirects user to correct page for the *Token Flow*
    , ie when response_type=token
    The /authorize endpoint should return an access_token
    """

    user = login(flask_client)
    client = Client.create_new("test client", user.id)

    Session.commit()
    domain = random_domain()
    uri = f"https://{domain}/callback"
    RedirectUri.create(
        client_id=client.id,
        uri=uri,
        commit=True,
    )

    # user allows client on the authorization page
    r = flask_client.post(
        url_for(
            "oauth.authorize",
            client_id=client.oauth_client_id,
            state="teststate",
            redirect_uri=uri,
            response_type="token",  # token flow
        ),
        data={"button": "allow", "suggested-email": "x@y.z", "suggested-name": "AB CD"},
        # user will be redirected to client page, do not allow redirection here
        # to assert the redirect url
        # follow_redirects=True,
    )

    assert r.status_code == 302  # user gets redirected back to client page

    # r.location will have this form http://localhost?state=teststate&code=knuyjepwvg
    o = urlparse(r.location)
    assert o.netloc == domain

    # in token flow, access_token is in fragment and not query
    assert o.fragment
    assert not o.query

    # parse the fragment, should return something like
    # {'state': ['teststate'], 'access_token': ['knuyjepwvg']}
    queries = parse_qs(o.fragment)
    assert len(queries) == 2

    assert queries["state"] == ["teststate"]

    # access_token must be returned
    assert len(queries["access_token"]) == 1


def test_authorize_id_token_flow(flask_client):
    """make sure the authorize redirects user to correct page for the *ID-Token Flow*
    , ie when response_type=id_token
    The /authorize endpoint should return an id_token
    """

    user = login(flask_client)
    client = Client.create_new("test client", user.id)

    Session.commit()
    domain = random_domain()
    uri = f"https://{domain}/callback"
    RedirectUri.create(
        client_id=client.id,
        uri=uri,
        commit=True,
    )

    # user allows client on the authorization page
    r = flask_client.post(
        url_for(
            "oauth.authorize",
            client_id=client.oauth_client_id,
            state="teststate",
            redirect_uri=uri,
            response_type="id_token",  # id_token flow
        ),
        data={"button": "allow", "suggested-email": "x@y.z", "suggested-name": "AB CD"},
        # user will be redirected to client page, do not allow redirection here
        # to assert the redirect url
        # follow_redirects=True,
    )

    assert r.status_code == 302  # user gets redirected back to client page

    # r.location will have this form http://localhost?state=teststate&code=knuyjepwvg
    o = urlparse(r.location)
    assert o.netloc == domain
    assert not o.fragment
    assert o.query

    # parse the fragment, should return something like
    # {'state': ['teststate'], 'id_token': ['knuyjepwvg']}
    queries = parse_qs(o.query)
    assert len(queries) == 2

    assert queries["state"] == ["teststate"]

    # access_token must be returned
    assert len(queries["id_token"]) == 1

    # id_token must be a valid, correctly signed JWT
    assert verify_id_token(queries["id_token"][0])


def test_authorize_token_id_token_flow(flask_client):
    """make sure the authorize redirects user to correct page for the *ID-Token Token Flow*
    , ie when response_type=id_token,token
    The /authorize endpoint should return an id_token and access_token
    id_token, once decoded, should contain *at_hash* in payload
    """

    user = login(flask_client)
    client = Client.create_new("test client", user.id)

    Session.commit()
    domain = random_domain()
    uri = f"https://{domain}/callback"
    RedirectUri.create(
        client_id=client.id,
        uri=uri,
        commit=True,
    )

    # user allows client on the authorization page
    r = flask_client.post(
        url_for(
            "oauth.authorize",
            client_id=client.oauth_client_id,
            state="teststate",
            redirect_uri=uri,
            response_type="id_token token",  # id_token,token flow
        ),
        data={"button": "allow", "suggested-email": "x@y.z", "suggested-name": "AB CD"},
        # user will be redirected to client page, do not allow redirection here
        # to assert the redirect url
        # follow_redirects=True,
    )

    assert r.status_code == 302  # user gets redirected back to client page

    # r.location will have this form http://localhost?state=teststate&code=knuyjepwvg
    o = urlparse(r.location)
    assert o.netloc == domain
    assert o.fragment
    assert not o.query

    # parse the fragment, should return something like
    # {'state': ['teststate'], 'id_token': ['knuyjepwvg']}
    queries = parse_qs(o.fragment)
    assert len(queries) == 3

    assert queries["state"] == ["teststate"]

    # access_token must be returned
    assert len(queries["id_token"]) == 1
    assert len(queries["access_token"]) == 1

    # id_token must be a valid, correctly signed JWT
    id_token = queries["id_token"][0]
    assert verify_id_token(id_token)

    # make sure jwt has all the necessary fields
    jwt = decode_id_token(id_token)

    # payload should have this format
    # {
    #   'at_hash': 'jLDmoGpuOIHwxeyFEe9SKw',
    #   'aud': 'testclient-sywcpwsyua',
    #   'auth_time': 1565450736,
    #   'avatar_url': None,
    #   'client': 'test client',
    #   'email': 'x@y.z',
    #   'email_verified': True,
    #   'exp': 1565454336,
    #   'iat': 1565450736,
    #   'id': 1,
    #   'iss': 'http://localhost',
    #   'name': 'AB CD',
    #   'sub': '1'
    # }
    payload = json.loads(jwt.claims)

    # at_hash MUST be present when the flow is id_token,token
    assert "at_hash" in payload

    assert "aud" in payload
    assert "auth_time" in payload
    assert "avatar_url" in payload
    assert "client" in payload
    assert "email" in payload
    assert "email_verified" in payload
    assert "exp" in payload
    assert "iat" in payload
    assert "id" in payload
    assert "iss" in payload
    assert "name" in payload
    assert "sub" in payload


def test_authorize_code_id_token_flow(flask_client):
    """make sure the authorize redirects user to correct page for the *ID-Token Code Flow*
    , ie when response_type=id_token,code
    The /authorize endpoint should return an id_token, code and id_token must contain *c_hash*

    The /token endpoint must return a access_token and an id_token

    """

    user = login(flask_client)
    client = Client.create_new("test client", user.id)

    Session.commit()
    domain = random_domain()
    uri = f"https://{domain}/callback"
    RedirectUri.create(
        client_id=client.id,
        uri=uri,
        commit=True,
    )

    # user allows client on the authorization page
    r = flask_client.post(
        url_for(
            "oauth.authorize",
            client_id=client.oauth_client_id,
            state="teststate",
            redirect_uri=uri,
            response_type="id_token code",  # id_token,code flow
        ),
        data={"button": "allow", "suggested-email": "x@y.z", "suggested-name": "AB CD"},
        # user will be redirected to client page, do not allow redirection here
        # to assert the redirect url
        # follow_redirects=True,
    )

    assert r.status_code == 302  # user gets redirected back to client page

    # r.location will have this form http://localhost?state=teststate&code=knuyjepwvg
    o = urlparse(r.location)
    assert o.netloc == domain
    assert not o.fragment
    assert o.query

    # parse the query, should return something like
    # {'state': ['teststate'], 'id_token': ['knuyjepwvg'], 'code': ['longstring']}
    queries = parse_qs(o.query)
    assert len(queries) == 3

    assert queries["state"] == ["teststate"]

    assert len(queries["id_token"]) == 1
    assert len(queries["code"]) == 1

    # id_token must be a valid, correctly signed JWT
    id_token = queries["id_token"][0]
    assert verify_id_token(id_token)

    # make sure jwt has all the necessary fields
    jwt = decode_id_token(id_token)

    # payload should have this format
    # {
    #   'at_hash': 'jLDmoGpuOIHwxeyFEe9SKw',
    #   'aud': 'testclient-sywcpwsyua',
    #   'auth_time': 1565450736,
    #   'avatar_url': None,
    #   'client': 'test client',
    #   'email': 'x@y.z',
    #   'email_verified': True,
    #   'exp': 1565454336,
    #   'iat': 1565450736,
    #   'id': 1,
    #   'iss': 'http://localhost',
    #   'name': 'AB CD',
    #   'sub': '1'
    # }
    payload = json.loads(jwt.claims)

    # at_hash MUST be present when the flow is id_token,token
    assert "c_hash" in payload

    assert "aud" in payload
    assert "auth_time" in payload
    assert "avatar_url" in payload
    assert "client" in payload
    assert "email" in payload
    assert "email_verified" in payload
    assert "exp" in payload
    assert "iat" in payload
    assert "id" in payload
    assert "iss" in payload
    assert "name" in payload
    assert "sub" in payload

    # <<< Exchange the code to get access_token >>>
    basic_auth_headers = base64.b64encode(
        f"{client.oauth_client_id}:{client.oauth_client_secret}".encode()
    ).decode("utf-8")

    r = flask_client.post(
        url_for("oauth.token"),
        headers={"Authorization": "Basic " + basic_auth_headers},
        data={"grant_type": "authorization_code", "code": queries["code"][0]},
    )

    # r.json should have this format
    # {
    #   'access_token': 'avmhluhonsouhcwwailydwvhankspptgidoggcbu',
    #   'id_token': 'ab.cd.xy',
    #   'expires_in': 3600,
    #   'scope': '',
    #   'token_type': 'bearer',
    #   'user': {
    #     'avatar_url': None,
    #     'client': 'test client',
    #     'email': 'x@y.z',
    #     'email_verified': True,
    #     'id': 1,
    #     'name': 'AB CD'
    #   }
    # }
    assert r.status_code == 200
    assert r.json["access_token"]
    assert r.json["expires_in"] == 3600
    assert not r.json["scope"]
    assert r.json["token_type"] == "Bearer"

    client_user = ClientUser.get_by(client_id=client.id)

    assert r.json["user"] == {
        "avatar_url": None,
        "client": "test client",
        "email": "x@y.z",
        "email_verified": True,
        "id": client_user.id,
        "name": "AB CD",
        "sub": str(client_user.id),
    }

    # id_token must be returned
    assert r.json["id_token"]

    # id_token must be a valid, correctly signed JWT
    assert verify_id_token(r.json["id_token"])


def test_authorize_page_invalid_client_id(flask_client):
    """make sure to redirect user to redirect_url?error=invalid_client_id"""
    user = login(flask_client)
    Client.create_new("test client", user.id)

    Session.commit()

    r = flask_client.get(
        url_for(
            "oauth.authorize",
            client_id="invalid_client_id",
            state="teststate",
            redirect_uri="http://localhost",
            response_type="code",
        )
    )

    assert r.status_code == 302
    assert r.location == url_for("auth.login")


def test_authorize_page_http_not_allowed(flask_client):
    """make sure to redirect user to redirect_url?error=http_not_allowed"""
    user = login(flask_client)
    client = Client.create_new("test client", user.id)
    client.approved = True

    Session.commit()

    r = flask_client.get(
        url_for(
            "oauth.authorize",
            client_id=client.oauth_client_id,
            state="teststate",
            redirect_uri="http://mywebsite.com",
            response_type="code",
        )
    )

    assert r.status_code == 302
    assert r.location == url_for("dashboard.index")


def test_authorize_page_unknown_redirect_uri(flask_client):
    """make sure to redirect user to redirect_url?error=unknown_redirect_uri"""
    user = login(flask_client)
    client = Client.create_new("test client", user.id)
    client.approved = True

    Session.commit()

    r = flask_client.get(
        url_for(
            "oauth.authorize",
            client_id=client.oauth_client_id,
            state="teststate",
            redirect_uri="https://unknown.com",
            response_type="code",
        )
    )

    assert r.status_code == 302
    assert r.location == url_for("dashboard.index")
