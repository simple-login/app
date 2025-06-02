import arrow

from app.db import Session
from app.log import LOG
from app.models import Notification


def cleanup_old_notifications(oldest_allowed: arrow.Arrow):
    LOG.i(f"Deleting notifications older than {oldest_allowed}")
    count = Notification.filter(Notification.created_at < oldest_allowed).delete()
    Session.commit()
    LOG.i(f"Deleted {count} notifications")
