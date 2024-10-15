from typing import Optional

from arrow import Arrow

from app.models import PartnerUser, PartnerSubscription
from app.user_audit_log_utils import emit_user_audit_log, UserAuditLogAction


def create_partner_user(
    user_id: int, partner_id: int, partner_email: str, external_user_id: str
) -> PartnerUser:
    instance = PartnerUser.create(
        user_id=user_id,
        partner_id=partner_id,
        partner_email=partner_email,
        external_user_id=external_user_id,
    )
    emit_user_audit_log(
        user_id=user_id,
        action=UserAuditLogAction.LinkAccount,
        message=f"Linked account to partner_id={partner_id} | partner_email={partner_email} | external_user_id={external_user_id}",
    )

    return instance


def create_partner_subscription(
    partner_user: PartnerUser,
    expiration: Optional[Arrow],
    msg: Optional[str] = None,
) -> PartnerSubscription:
    instance = PartnerSubscription.create(
        partner_user_id=partner_user.id,
        end_at=expiration,
    )

    message = "User upgraded through partner subscription"
    if msg:
        message += f" | {msg}"
    emit_user_audit_log(
        user_id=partner_user.user_id,
        action=UserAuditLogAction.Upgrade,
        message=message,
    )

    return instance
