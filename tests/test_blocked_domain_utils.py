from app.blocked_domain_utils import is_domain_blocked
from app.db import Session
from app.models import BlockedDomain
from tests.utils import create_new_user


def setup():
    user = create_new_user()
    BlockedDomain.create(
        user_id=user.id,
        domain="example.com",
        flush=True,
    )
    Session.flush()


def teardown_module():
    Session.query(BlockedDomain).delete()


def test_domain_blocked_for_user():
    user = create_new_user()
    BlockedDomain.create(
        user_id=user.id,
        domain="example.com",
        flush=True,
    )
    Session.flush()

    assert is_domain_blocked(user.id, "example.com")
    assert not is_domain_blocked(user.id, "some-other-example.com")
