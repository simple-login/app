from enum import Enum
from typing import Optional

from app.models import User, AbuserAuditLog


class AbuserAuditLogAction(Enum):
    MarkAbuser = "mark_abuser"
    UnmarkAbuser = "unmark_abuser"
    GetAbuserBundles = "get_abuser_bundles"


def emit_abuser_audit_log(
    user: User,
    action: AbuserAuditLogAction,
    message: str,
    admin: Optional[User] = None,
    commit: bool = False,
) -> None:
    AbuserAuditLog.create(
        user_id=user.id,
        action=action.value,
        message=message,
        admin_id=admin.id if admin else None,
        commit=commit,
    )
