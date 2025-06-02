import arrow

from app.db import Session
from app.log import LOG
from app.models import UserAuditLog


def cleanup_user_audit_log(oldest_allowed: arrow.Arrow):
    LOG.i(f"Deleting user_audit_log older than {oldest_allowed}")
    count = UserAuditLog.filter(UserAuditLog.created_at < oldest_allowed).delete()
    Session.commit()
    LOG.i(f"Deleted {count} user_audit_log entries")
