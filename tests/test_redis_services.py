import uuid
from datetime import datetime, timezone
from unittest.mock import Mock

import flask
import pytest
from flask_limiter import Limiter
from werkzeug.exceptions import TooManyRequests

from app import parallel_limiter, rate_limiter, redis_services
from app.session import RedisSessionStore


@pytest.fixture
def redis_app(monkeypatch):
    # Initialization changes module globals; restore the main app's clients afterwards.
    monkeypatch.setattr(parallel_limiter, "lock_redis", None)
    monkeypatch.setattr(rate_limiter, "lock_redis", None)
    monkeypatch.setattr(rate_limiter, "rateLimitsEnabled", True)
    app = flask.Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="redis-services-test")
    return app


@pytest.mark.parametrize("scheme", ["redis", "rediss", "redis+unix"])
def test_redis_storage_initialization(redis_app, monkeypatch, scheme):
    storage = Mock()
    factory = Mock(return_value=storage)
    monkeypatch.setattr(redis_services.limits.storage, "RedisStorage", factory)
    uri = (
        f"{scheme}:///tmp/redis.sock"
        if scheme == "redis+unix"
        else f"{scheme}://localhost"
    )

    redis_services.initialize_redis_services(redis_app, uri)

    factory.assert_called_once_with(uri)
    assert isinstance(redis_app.session_interface, RedisSessionStore)
    assert redis_app.session_interface._redis_w is storage.storage
    assert redis_app.session_interface._redis_r is storage.storage
    assert parallel_limiter.lock_redis is storage
    assert rate_limiter.lock_redis is storage


def test_sentinel_storage_initialization(redis_app, monkeypatch):
    storage = Mock()
    factory = Mock(return_value=storage)
    monkeypatch.setattr(redis_services.limits.storage, "RedisSentinelStorage", factory)
    uri = "redis+sentinel://localhost:26379/mymaster"

    redis_services.initialize_redis_services(redis_app, uri)

    factory.assert_called_once_with(uri)
    assert redis_app.session_interface._redis_w is storage.storage
    assert redis_app.session_interface._redis_r is storage.storage_slave
    assert parallel_limiter.lock_redis is storage
    assert rate_limiter.lock_redis is storage


def test_invalid_storage_url(redis_app):
    with pytest.raises(RuntimeError, match="invalid redis url"):
        redis_services.initialize_redis_services(redis_app, "memory://")


@pytest.fixture
def unix_redis_url():
    return "redis+unix:///tmp/redis/redis.sock?db=1"


def test_unix_socket_sessions(redis_app, unix_redis_url):
    redis_services.initialize_redis_services(redis_app, unix_redis_url)

    @redis_app.route("/")
    def count():
        flask.session["visits"] = flask.session.get("visits", 0) + 1
        return str(flask.session["visits"])

    client = redis_app.test_client()
    assert client.get("/").data == b"1"
    assert client.get("/").data == b"2"
    assert redis_app.test_client().get("/").data == b"1"
    storage = redis_app.session_interface._redis_w
    assert storage.connection_pool.connection_kwargs["db"] == 1


def test_unix_socket_concurrency_lock(redis_app, unix_redis_url):
    redis_services.initialize_redis_services(redis_app, unix_redis_url)
    lock = parallel_limiter._InnerLock()
    name = str(uuid.uuid4())
    lock.acquire_lock(name, "owner")
    try:
        with pytest.raises(TooManyRequests):
            lock.acquire_lock(name, "competitor")
        lock.release_lock(name, "competitor")
        assert parallel_limiter.lock_redis.storage.get(name) == b"owner"
    finally:
        lock.release_lock(name, "owner")
    lock.acquire_lock(name, "next-owner")
    lock.release_lock(name, "next-owner")


def test_unix_socket_bucket_limit(redis_app, unix_redis_url, monkeypatch):
    clock = Mock()
    clock.now.return_value = datetime(2025, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(rate_limiter, "datetime", clock)
    redis_services.initialize_redis_services(redis_app, unix_redis_url)
    name = str(uuid.uuid4())
    rate_limiter.check_bucket_limit(name, max_hits=1)
    with pytest.raises(TooManyRequests):
        rate_limiter.check_bucket_limit(name, max_hits=1)


def test_unix_socket_flask_limiter(redis_app, unix_redis_url):
    redis_services.initialize_redis_services(redis_app, unix_redis_url)
    redis_app.config["RATELIMIT_STORAGE_URL"] = unix_redis_url
    key = str(uuid.uuid4())
    limiter = Limiter(redis_app, key_func=lambda: key)

    @redis_app.route("/")
    @limiter.limit("1/minute")
    def limited():
        return "ok"

    client = redis_app.test_client()
    assert client.get("/").status_code == 200
    assert client.get("/").status_code == 429
