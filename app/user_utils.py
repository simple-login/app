import arrow

from app.db import Session
from app.log import LOG
from app.models import User, ApiKey
from app.session import logout_session
from app.user_audit_log_utils import emit_user_audit_log, UserAuditLogAction


def soft_delete_user(user: User, source: str):
    LOG.i(f"Marked user {user} for soft-deletion")
    emit_user_audit_log(
        user=user,
        action=UserAuditLogAction.UserMarkedForDeletion,
        message=f"Marked user {user} ({user.email}) for deletion from {source}",
    )
    user.delete_on = arrow.utcnow()
    ApiKey.filter_by(user_id=user.id).delete()
    Session.commit()
    logout_session()
