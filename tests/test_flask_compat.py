import flask
import pytest

from app.flask_compat import apply_flask_compat
from app.user_agent import ParsedUserAgent


@pytest.fixture
def compat_app():
    app = flask.Flask(__name__)
    apply_flask_compat(app)

    @app.route("/json-body", methods=["POST", "DELETE"])
    def json_body():
        return flask.jsonify(body=flask.request.get_json())

    @app.route("/bytes")
    def bytes_value():
        return flask.jsonify(value=b"signed.value")

    @app.route("/redirect")
    def do_redirect():
        return flask.redirect("/target")

    @app.route("/browser")
    def browser():
        ua = flask.request.user_agent
        return flask.jsonify(browser=ua.browser, platform=ua.platform)

    return app


def test_get_json_without_json_content_type_returns_none(compat_app):
    r = compat_app.test_client().delete("/json-body")
    assert r.status_code == 200
    assert r.json == {"body": None}


def test_get_json_with_invalid_json_is_bad_request(compat_app):
    r = compat_app.test_client().post(
        "/json-body", data="{not json", content_type="application/json"
    )
    assert r.status_code == 400


def test_jsonify_serializes_bytes_as_str(compat_app):
    r = compat_app.test_client().get("/bytes")
    assert r.json == {"value": "signed.value"}


def test_location_header_is_absolute(compat_app):
    r = compat_app.test_client().get("/redirect", base_url="https://sl.lan")
    assert r.headers["Location"] == "https://sl.lan/target"


def test_user_agent_is_parsed(compat_app):
    r = compat_app.test_client().get(
        "/browser",
        headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 "
            "Safari/604.1"
        },
    )
    assert r.json == {"browser": "safari", "platform": "iphone"}


@pytest.mark.parametrize(
    "ua,browser,platform",
    [
        (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/102.0.0.0 Safari/537.36",
            "chrome",
            "linux",
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 "
            "Firefox/121.0",
            "firefox",
            "macos",
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like "
            "Gecko) Chrome/70.0.3538.102 Safari/537.36 Edge/18.19582",
            "edge",
            "windows",
        ),
        ("curl/8.4.0", None, None),
    ],
)
def test_parsed_user_agent(ua, browser, platform):
    parsed = ParsedUserAgent(ua)
    assert parsed.browser == browser
    assert parsed.platform == platform
