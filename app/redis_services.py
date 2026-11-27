import flask
import limits.storage

from app import config
from app.parallel_limiter import set_redis_concurrent_lock
from app.rate_limiter import set_redis_concurrent_lock as rate_limit_set_redis
from app.session import RedisSessionStore

REDIS_STORAGE_EXTENSION = "sl_redis_storage"


def redis_storage_options(redis_url: str) -> dict:
    timeouts = {
        "socket_timeout": config.MEM_STORE_SOCKET_TIMEOUT,
        "socket_connect_timeout": config.MEM_STORE_SOCKET_TIMEOUT,
    }
    options = {**timeouts, "socket_keepalive": True, "health_check_interval": 30}
    if redis_url.startswith("redis+sentinel://"):
        options["sentinel_kwargs"] = timeouts
    return options


def initialize_redis_services(app: flask.Flask, redis_url: str):
    options = redis_storage_options(redis_url)
    if redis_url.startswith("redis://") or redis_url.startswith("rediss://"):
        storage = limits.storage.RedisStorage(redis_url, **options)
        app.session_interface = RedisSessionStore(storage.storage, storage.storage, app)
        set_redis_concurrent_lock(storage)
        rate_limit_set_redis(storage)
    elif redis_url.startswith("redis+sentinel://"):
        storage = limits.storage.RedisSentinelStorage(redis_url, **options)
        app.session_interface = RedisSessionStore(
            storage.storage, storage.storage_slave, app
        )
        set_redis_concurrent_lock(storage)
        rate_limit_set_redis(storage)
    else:
        raise RuntimeError(
            f"Tried to set_redis_session with an invalid redis url: ${redis_url}"
        )
    app.extensions[REDIS_STORAGE_EXTENSION] = storage
