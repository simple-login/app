import flask
import limits.storage

from app.parallel_limiter import set_redis_concurrent_lock
from app.rate_limiter import set_redis_concurrent_lock as rate_limit_set_redis
from app.session import RedisSessionStore


def initialize_redis_services(app: flask.Flask, redis_url: str):
    if redis_url.startswith("redis://") or redis_url.startswith("rediss://"):
        storage = limits.storage.RedisStorage(redis_url)
        app.session_interface = RedisSessionStore(storage.storage, storage.storage, app)
        set_redis_concurrent_lock(storage)
        rate_limit_set_redis(storage)
    elif redis_url.startswith("redis+sentinel://"):
        storage = limits.storage.RedisSentinelStorage(redis_url)
        app.session_interface = RedisSessionStore(
            storage.storage, storage.storage_slave, app
        )
        set_redis_concurrent_lock(storage)
        rate_limit_set_redis(storage)
    else:
        raise RuntimeError(
            f"Tried to set_redis_session with an invalid redis url: ${redis_url}"
        )
