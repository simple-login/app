from datetime import datetime
from typing import Optional

import redis.exceptions
import werkzeug.exceptions
from limits.storage import RedisStorage

from app.log import log

lock_redis: Optional[RedisStorage] = None


def set_redis_concurrent_lock(redis: RedisStorage):
    global lock_redis
    lock_redis = redis


def check_bucket_limit(
    lock_name: Optional[str] = None,
    max_hits: int = 5,
    bucket_seconds: int = 3600,
):
    # Calculate current bucket time
    bucket_id = int(datetime.utcnow().timestamp()) % bucket_seconds
    bucket_lock_name = f"bl:{lock_name}:{bucket_id}"
    if not lock_redis:
        return
    try:
        value = lock_redis.incr(bucket_lock_name, bucket_seconds)
        if value > max_hits:
            raise werkzeug.exceptions.TooManyRequests()
    except (redis.exceptions.RedisError, AttributeError):
        log.e("Cannot connect to redis")
