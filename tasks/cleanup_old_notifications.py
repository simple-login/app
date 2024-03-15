import arrow

from app.log import LOG
from app.models import Notification


def cleanup_old_notifications():
    count = Notification.filter(
        Notification.created_at < arrow.now().shift(days=-15)
    ).delete()
    LOG.i(f"Deleted {count} notifications")
