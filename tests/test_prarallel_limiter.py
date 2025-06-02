import threading
import time
from typing import Optional

import werkzeug.exceptions
from flask_login import login_user

from app.parallel_limiter import _InnerLock
from tests.utils import create_new_user


def test_parallel_limiter(flask_app):
    user = create_new_user()
    with flask_app.test_request_context():
        login_user(user)
        pl = _InnerLock("test", max_wait_secs=1)
        for loop_id in range(10):
            assert pl(lambda x: x)(loop_id) == loop_id


def sleep_thread(pl: _InnerLock, sem: Optional[threading.Semaphore] = None):
    if sem is not None:
        sem.release()
    pl(time.sleep)(1)


def test_too_many_requests(flask_app):
    user = create_new_user()
    with flask_app.test_request_context():
        login_user(user)
        sem = threading.Semaphore(0)
        pl = _InnerLock("test", max_wait_secs=5)
        t = threading.Thread(target=sleep_thread, args=(pl, sem))
        t.daemon = True
        t.start()
        sem.acquire()
        try:
            got_exception = False
            pl(sleep_thread)(pl)
        except werkzeug.exceptions.TooManyRequests:
            got_exception = True
        assert got_exception
