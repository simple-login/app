from http import HTTPStatus
from random import Random

from flask import g

from app import config
from app.extensions import limiter
from tests.conftest import app as test_app
from tests.utils import login

# IMPORTANT NOTICE
# ----------------
# This test file has a special behaviour. After each request, a call to fix_rate_limit_after_request must
# be performed, in order for the rate_limiting process to work appropriately in test time.
# If you want to see why, feel free to refer to the source of the "hack":
# https://github.com/alisaifee/flask-limiter/issues/147#issuecomment-642683820

_ENDPOINT = "/tests/internal/rate_limited"
_MAX_PER_MINUTE = 3


@test_app.route(
    _ENDPOINT,
    methods=["GET"],
)
@limiter.limit(f"{_MAX_PER_MINUTE}/minute")
def rate_limited_endpoint_1():
    return "Working", HTTPStatus.OK


def random_ip() -> str:
    rand = Random()
    octets = [str(rand.randint(0, 255)) for _ in range(4)]
    return ".".join(octets)


def fix_rate_limit_after_request():
    g._rate_limiting_complete = False


def request_headers(source_ip: str) -> dict:
    return {"X-Forwarded-For": source_ip}


def test_rate_limit_limits_by_source_ip(flask_client):
    config.DISABLE_RATE_LIMIT = False
    source_ip = random_ip()

    for _ in range(_MAX_PER_MINUTE):
        res = flask_client.get(_ENDPOINT, headers=request_headers(source_ip))
        fix_rate_limit_after_request()
        assert res.status_code == HTTPStatus.OK

    res = flask_client.get(_ENDPOINT, headers=request_headers(source_ip))
    fix_rate_limit_after_request()
    assert res.status_code == HTTPStatus.TOO_MANY_REQUESTS

    # Check that changing the "X-Forwarded-For" allows the request to succeed
    res = flask_client.get(_ENDPOINT, headers=request_headers(random_ip()))
    fix_rate_limit_after_request()
    assert res.status_code == HTTPStatus.OK


def test_rate_limit_limits_by_user_id(flask_client):
    config.DISABLE_RATE_LIMIT = False
    # Login with a user
    login(flask_client)
    fix_rate_limit_after_request()

    # Run the N requests with a different source IP but with the same user
    for _ in range(_MAX_PER_MINUTE):
        res = flask_client.get(_ENDPOINT, headers=request_headers(random_ip()))
        fix_rate_limit_after_request()
        assert res.status_code == HTTPStatus.OK

    res = flask_client.get(_ENDPOINT, headers=request_headers(random_ip()))
    fix_rate_limit_after_request()
    assert res.status_code == HTTPStatus.TOO_MANY_REQUESTS


def test_rate_limit_limits_by_user_id_ignoring_ip(flask_client):
    config.DISABLE_RATE_LIMIT = False
    source_ip = random_ip()

    # Login with a user
    login(flask_client)
    fix_rate_limit_after_request()

    # Run the N requests with a different source IP but with the same user
    for _ in range(_MAX_PER_MINUTE):
        res = flask_client.get(_ENDPOINT, headers=request_headers(source_ip))
        fix_rate_limit_after_request()
        assert res.status_code == HTTPStatus.OK

    res = flask_client.get(_ENDPOINT)
    fix_rate_limit_after_request()
    assert res.status_code == HTTPStatus.TOO_MANY_REQUESTS

    # Log out
    flask_client.cookie_jar.clear()

    # Log in with another user
    login(flask_client)
    fix_rate_limit_after_request()

    # Run the request again, reusing the same IP as before
    res = flask_client.get(_ENDPOINT, headers=request_headers(source_ip))
    fix_rate_limit_after_request()
    assert res.status_code == HTTPStatus.OK
