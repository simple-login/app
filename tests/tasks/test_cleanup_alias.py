import arrow

from app.models import Job, Alias
from tasks.cleanup_alias import cleanup_alias
from tests.utils import create_new_user, random_email


def test_cleanup_alias():
    Job.filter().delete()
    user = create_new_user()

    now = arrow.utcnow()
    alias_expired = Alias.create(
        user_id=user.id,
        email=random_email(),
        mailbox_id=user.default_mailbox_id,
        delete_on=now.shift(minutes=-1),
    ).id
    alias_not_expired = Alias.create(
        user_id=user.id,
        email=random_email(),
        mailbox_id=user.default_mailbox_id,
        delete_on=now.shift(minutes=1),
    ).id
    alias_not_pending = Alias.create(
        user_id=user.id,
        email=random_email(),
        mailbox_id=user.default_mailbox_id,
    ).id
    cleanup_alias(now)
    assert Alias.get(alias_not_expired) is not None
    assert Alias.get(alias_not_pending) is not None
    assert Alias.get(alias_expired) is None
