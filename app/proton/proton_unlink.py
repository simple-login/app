from newrelic import agent

from app.db import Session
from app.events.event_dispatcher import EventDispatcher
from app.events.generated.event_pb2 import EventContent, UserUnlinked
from app.log import LOG
from app.models import User, PartnerUser
from app.proton.proton_partner import get_proton_partner
from app.user_audit_log_utils import emit_user_audit_log, UserAuditLogAction


def can_unlink_proton_account(user: User) -> bool:
    return (user.flags & User.FLAG_CREATED_FROM_PARTNER) == 0


def perform_proton_account_unlink(
    current_user: User, skip_check: bool = False
) -> None | str:
    if not skip_check and not can_unlink_proton_account(current_user):
        return None
    proton_partner = get_proton_partner()
    partner_user = PartnerUser.get_by(
        user_id=current_user.id, partner_id=proton_partner.id
    )
    if partner_user is not None:
        LOG.info(f"User {current_user} has unlinked the account from {partner_user}")
        emit_user_audit_log(
            user=current_user,
            action=UserAuditLogAction.UnlinkAccount,
            message=f"User has unlinked the account (email={partner_user.partner_email} | external_user_id={partner_user.external_user_id})",
        )
        EventDispatcher.send_event(
            partner_user.user, EventContent(user_unlinked=UserUnlinked())
        )
        PartnerUser.delete(partner_user.id)
    external_user_id = partner_user.external_user_id
    Session.commit()
    agent.record_custom_event("AccountUnlinked", {"partner": proton_partner.name})
    return external_user_id
