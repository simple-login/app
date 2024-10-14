import arrow

from app.db import Session
from app.log import LOG
from app.models import AliasAuditLog


def cleanup_alias_audit_log(oldest_allowed: arrow.Arrow):
    LOG.i(f"Deleting alias_audit_log older than {oldest_allowed}")
    count = AliasAuditLog.filter(AliasAuditLog.created_at < oldest_allowed).delete()
    Session.commit()
    LOG.i(f"Deleted {count} alias_audit_log entries")
