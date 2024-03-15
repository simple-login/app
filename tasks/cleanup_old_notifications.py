import arrow

from app.log import LOG
from app.models import Notification


def cleanup_old_notifications(oldest_allowed: arrow.Arrow):
    count = Notification.filter(Notification.created_at < oldest_allowed).delete()
    LOG.i(f"Deleted {count} notifications")
