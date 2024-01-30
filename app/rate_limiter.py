from typing import Optional

import redis.exceptions
from flask_limiter import RateLimitExceeded
from limits.storage import RedisStorage

from app.log import log

lock_redis: Optional[RedisStorage] = None


def set_redis_concurrent_lock(redis: RedisStorage):
    global lock_redis
    lock_redis = redis


def check_limit(
    lock_name: Optional[str] = None,
    max_hits: int = 5,
    expiration_time: int = 3600,
):
    try:
        value = lock_redis.incr(lock_name, expiration_time)
        if value > max_hits:
            return RateLimitExceeded(lock_name)
    except redis.exceptions.RedisError:
        log.e("Cannot connect to redis")
