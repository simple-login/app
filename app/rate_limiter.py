from datetime import datetime, UTC
from typing import Optional

import newrelic.agent
import redis.exceptions
import werkzeug.exceptions
from limits.storage import RedisStorage

from app.log import LOG

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
    int_time = int(datetime.now(UTC).timestamp())
    bucket_id = int_time - (int_time % bucket_seconds)
    bucket_lock_name = f"bl:{lock_name}:{bucket_id}"
    if not lock_redis:
        return
    try:
        value = lock_redis.incr(bucket_lock_name, bucket_seconds)
        if value > max_hits:
            LOG.i(
                f"Rate limit hit for {lock_name} (bucket id {bucket_id}) -> {value}/{max_hits}"
            )
            newrelic.agent.record_custom_event(
                "BucketRateLimit",
                {"lock_name": lock_name, "bucket_seconds": bucket_seconds},
            )
            raise werkzeug.exceptions.TooManyRequests()
    except (redis.exceptions.RedisError, AttributeError):
        LOG.e("Cannot connect to redis")
