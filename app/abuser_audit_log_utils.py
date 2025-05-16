from enum import Enum

from app.models import User, AbuserAuditLog


class AbuserAuditLogAction(Enum):
    MarkAbuser = "mark_abuser"
    UnmarkAbuser = "unmark_abuser"
    GetAbuserBundles = "get_abuser_bundles"


def emit_abuser_audit_log(
    user: User,
    action: AbuserAuditLogAction,
    message: str,
    commit: bool = False,
) -> None:
    AbuserAuditLog.create(
        user_id=user.id,
        action=action.value,
        message=message,
        commit=commit,
    )
