from enum import Enum
from typing import Optional

from app.models import AbuserAuditLog


class AbuserAuditLogAction(Enum):
    MarkAbuser = "mark_abuser"
    UnmarkAbuser = "unmark_abuser"
    GetAbuserBundles = "get_abuser_bundles"


def emit_abuser_audit_log(
    user_id: int,
    action: AbuserAuditLogAction,
    message: str,
    admin_id: Optional[int] = None,
    commit: bool = False,
) -> None:
    AbuserAuditLog.create(
        user_id=user_id,
        action=action.value,
        message=message,
        admin_id=admin_id if admin_id else None,
        commit=commit,
    )
