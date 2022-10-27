import uuid
from datetime import timedelta
from functools import wraps
from typing import Callable, Any, Optional

from flask_login import current_user
from limits.storage import RedisStorage
from werkzeug import exceptions

lock_redis: Optional[RedisStorage] = None


def set_redis_concurrent_lock(redis: RedisStorage):
    global lock_redis
    lock_redis = redis


class _InnerLock:
    def __init__(
        self,
        lock_suffix: Optional[str] = None,
        max_wait_secs: int = 5,
        only_when: Optional[Callable[..., bool]] = None,
    ):
        self.lock_suffix = lock_suffix
        self.max_wait_secs = max_wait_secs
        self.only_when = only_when

    def acquire_lock(self, lock_name: str, lock_value: str):
        if not lock_redis.storage.set(
            lock_name, lock_value, ex=timedelta(seconds=self.max_wait_secs), nx=True
        ):
            raise exceptions.TooManyRequests()

    def release_lock(self, lock_name: str, lock_value: str):
        current_lock_value = lock_redis.storage.get(lock_name)
        if current_lock_value == lock_value.encode("utf-8"):
            lock_redis.storage.delete(lock_name)

    def __call__(self, f: Callable[..., Any]):

        if self.lock_suffix is None:
            lock_suffix = f.__name__
        else:
            lock_suffix = self.lock_suffix

        @wraps(f)
        def decorated(*args, **kwargs):
            if self.only_when and not self.only_when():
                return f(*args, **kwargs)
            if not lock_redis:
                return f(*args, **kwargs)

            lock_value = str(uuid.uuid4())[:10]
            lock_name = f"cl:{current_user.id}:{lock_suffix}"
            self.acquire_lock(lock_name, lock_value)
            try:
                return f(*args, **kwargs)
            finally:
                self.release_lock(lock_name, lock_value)

        return decorated


def lock(
    name: Optional[str] = None,
    max_wait_secs: int = 5,
    only_when: Optional[Callable[..., bool]] = None,
):
    return _InnerLock(name, max_wait_secs, only_when)
