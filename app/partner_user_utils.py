from typing import Optional

import arrow
from arrow import Arrow
from sqlalchemy.exc import IntegrityError

from app.constants import JobType
from app.db import Session
from app.models import PartnerUser, PartnerSubscription, User, Job
from app.user_audit_log_utils import emit_user_audit_log, UserAuditLogAction


def create_partner_user(
    user: User, partner_id: int, partner_email: str, external_user_id: str
) -> PartnerUser:
    instance = PartnerUser.create(
        user_id=user.id,
        partner_id=partner_id,
        partner_email=partner_email,
        external_user_id=external_user_id,
    )
    Job.create(
        name=JobType.SEND_ALIAS_CREATION_EVENTS.value,
        payload={"user_id": user.id},
        run_at=arrow.now(),
    )
    emit_user_audit_log(
        user=user,
        action=UserAuditLogAction.LinkAccount,
        message=f"Linked account to partner_id={partner_id} | partner_email={partner_email} | external_user_id={external_user_id}",
    )

    return instance


def create_partner_subscription(
    partner_user: PartnerUser,
    expiration: Optional[Arrow] = None,
    lifetime: bool = False,
    msg: Optional[str] = None,
) -> PartnerSubscription:
    message = "User upgraded through partner subscription"
    if msg:
        message += f" | {msg}"
    try:
        instance = PartnerSubscription.create(
            partner_user_id=partner_user.id,
            end_at=expiration,
            lifetime=lifetime,
        )

        emit_user_audit_log(
            user=partner_user.user,
            action=UserAuditLogAction.Upgrade,
            message=message,
        )
        Session.flush()
    except IntegrityError:
        Session.rollback()
        instance = PartnerSubscription.get_by(partner_user_id=partner_user.id)
        if not instance:
            raise RuntimeError("Missing partner subscription")
        if instance.lifetime != lifetime or instance.expiration != expiration:
            instance.expiration = expiration
            instance.lifetime = lifetime
            emit_user_audit_log(
                user=partner_user.user,
                action=UserAuditLogAction.Upgrade,
                message=message,
            )

    return instance
