import pytest

from app import readiness
from app.readiness import READINESS_PATH
from app.redis_services import REDIS_STORAGE_EXTENSION

AUTH = {"Authorization": "Bearer test-readiness-token"}


def test_ready_when_db_and_redis_are_up(flask_client):
    r = flask_client.get(READINESS_PATH, headers=AUTH)

    assert r.status_code == 200
    assert r.json == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": "test-readiness-token"},
        {"Authorization": "Basic test-readiness-token"},
    ],
)
def test_rejects_missing_or_wrong_token(flask_client, headers):
    r = flask_client.get(READINESS_PATH, headers=headers)

    assert r.status_code == 401
    assert r.data == b""


def test_not_ready_when_database_fails(flask_client, monkeypatch):
    def broken():
        raise RuntimeError("db down")

    monkeypatch.setitem(readiness.CHECKS, "database", broken)

    r = flask_client.get(READINESS_PATH, headers=AUTH)

    assert r.status_code == 503
    assert r.json == {"status": "fail", "checks": {"database": "fail", "redis": "ok"}}


class _BrokenRedisClient:
    def ping(self):
        raise ConnectionError("redis down")


class _BrokenStorage:
    storage = _BrokenRedisClient()


def test_not_ready_when_redis_fails(flask_client, flask_app, monkeypatch):
    monkeypatch.setitem(flask_app.extensions, REDIS_STORAGE_EXTENSION, _BrokenStorage())

    r = flask_client.get(READINESS_PATH, headers=AUTH)

    assert r.status_code == 503
    assert r.json == {"status": "fail", "checks": {"database": "ok", "redis": "fail"}}


def test_redis_disabled_without_mem_store(flask_client, flask_app, monkeypatch):
    monkeypatch.delitem(flask_app.extensions, REDIS_STORAGE_EXTENSION)

    r = flask_client.get(READINESS_PATH, headers=AUTH)

    assert r.status_code == 200
    assert r.json["checks"]["redis"] == "disabled"


def test_no_blueprint_without_token(monkeypatch):
    monkeypatch.setattr(readiness.config, "READINESS_TOKEN", None)

    assert readiness.create_readiness_blueprint() is None


@pytest.mark.parametrize("path", ["/health", READINESS_PATH])
def test_probes_do_not_persist_a_session(flask_client, path):
    r = flask_client.get(path, headers=AUTH)

    assert r.status_code == 200
    assert "Set-Cookie" not in r.headers


def test_regular_requests_still_get_a_session(flask_client):
    r = flask_client.get("/auth/login")

    assert "Set-Cookie" in r.headers
