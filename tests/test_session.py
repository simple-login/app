import json
import pickle

import flask

from app import config
from app.session import RedisSessionStore


class FakeRedis:
    def __init__(self):
        self.data = {}

    def get(self, name):
        return self.data.get(name)

    def setex(self, name, value, time):
        self.data[name] = value

    def delete(self, name):
        self.data.pop(name, None)


def _make_app():
    app = flask.Flask(__name__)
    app.secret_key = "test"
    app.session_cookie_name = "slapp"
    return app


def _store():
    redis = FakeRedis()
    return RedisSessionStore(redis, redis, _make_app()), redis


def _request_with_session_id(app, session_id):
    signed = RedisSessionStore._get_signer(app).sign(session_id.encode()).decode()
    return flask.Request.from_values(headers={"Cookie": f"slapp={signed}"})


def test_save_session_stores_json():
    app = _make_app()
    store, redis = _store()
    session = store.open_session(app, flask.Request.from_values())
    session["_user_id"] = "abc"
    store.save_session(app, session, flask.Response())

    raw = redis.data[RedisSessionStore._get_key(session.session_id)]
    assert json.loads(raw) == {"_user_id": "abc"}


def test_open_session_reads_json():
    app = _make_app()
    store, redis = _store()
    redis.data[RedisSessionStore._get_key("sid")] = json.dumps(
        {"_user_id": "abc"}
    ).encode()

    session = store.open_session(app, _request_with_session_id(app, "sid"))
    assert session.session_id == "sid"
    assert session["_user_id"] == "abc"


def test_open_session_does_not_unpickle_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "SESSION_PICKLE_FALLBACK", False)
    app = _make_app()
    store, redis = _store()
    redis.data[RedisSessionStore._get_key("sid")] = pickle.dumps({"_user_id": "abc"})

    session = store.open_session(app, _request_with_session_id(app, "sid"))
    assert session.session_id != "sid"
    assert "_user_id" not in session


def test_open_session_unpickles_legacy_value_with_fallback(monkeypatch):
    monkeypatch.setattr(config, "SESSION_PICKLE_FALLBACK", True)
    app = _make_app()
    store, redis = _store()
    redis.data[RedisSessionStore._get_key("sid")] = pickle.dumps({"_user_id": "abc"})

    session = store.open_session(app, _request_with_session_id(app, "sid"))
    assert session.session_id == "sid"
    assert session["_user_id"] == "abc"


def test_open_session_with_garbage_value(monkeypatch):
    monkeypatch.setattr(config, "SESSION_PICKLE_FALLBACK", True)
    app = _make_app()
    store, redis = _store()
    redis.data[RedisSessionStore._get_key("sid")] = b"\x00not a session"

    session = store.open_session(app, _request_with_session_id(app, "sid"))
    assert session.session_id != "sid"
    assert "_user_id" not in session
