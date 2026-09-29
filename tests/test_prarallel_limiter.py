import threading
import time

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


def test_too_many_requests(flask_app):
    user = create_new_user()
    sem = threading.Semaphore(0)
    pl = _InnerLock("test", max_wait_secs=5)

    def sleep_with_signal():
        sem.release()
        time.sleep(1)

    def run_in_thread():
        with flask_app.test_request_context():
            login_user(user)
            pl(sleep_with_signal)()

    t = threading.Thread(target=run_in_thread)
    t.daemon = True
    t.start()
    sem.acquire()

    with flask_app.test_request_context():
        login_user(user)
        got_exception = False
        try:
            pl(lambda: None)()
        except werkzeug.exceptions.TooManyRequests:
            got_exception = True

    assert got_exception
    t.join(timeout=2)
