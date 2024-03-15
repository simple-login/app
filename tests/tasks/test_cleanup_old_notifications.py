import arrow

from app.models import Notification
from tasks.cleanup_old_notifications import cleanup_old_notifications
from tests.utils import create_new_user


def test_cleanup_old_notifications():
    Notification.filter().delete()
    user = create_new_user()
    now = arrow.now()
    delete_id = Notification.create(
        user_id=user.id,
        created_at=now.shift(minutes=-1),
        message="",
        flush=True,
    ).id
    keep_id = Notification.create(
        user_id=user.id,
        created_at=now.shift(minutes=+1),
        message="",
        flush=True,
    ).id
    cleanup_old_notifications(now)
    assert Notification.get(id=delete_id) is None
    assert Notification.get(id=keep_id) is not None
