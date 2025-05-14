from enum import Enum
from typing import Optional

from app.models import User, AbuserAuditLog


class AbuserAuditLogAction(Enum):
    CreateUser = "create_user"


def emit_abuser_audit_log(
    user: Optional[User],
    action: AbuserAuditLogAction,
    message: str,
    commit: bool = False,
) -> None:
    AbuserAuditLog.create(
        user_id=user.id if user else -1,
        action=action.value,
        message=message,
        commit=commit,
    )
