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
