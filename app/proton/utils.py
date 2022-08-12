from newrelic import agent
from typing import Optional

from app.db import Session
from app.errors import ProtonPartnerNotSetUp
from app.models import Partner, PartnerUser, User

PROTON_PARTNER_NAME = "Proton"
_PROTON_PARTNER: Optional[Partner] = None


def get_proton_partner() -> Partner:
    global _PROTON_PARTNER
    if _PROTON_PARTNER is None:
        partner = Partner.get_by(name=PROTON_PARTNER_NAME)
        if partner is None:
            raise ProtonPartnerNotSetUp
        Session.expunge(partner)
        _PROTON_PARTNER = partner
    return _PROTON_PARTNER


def is_proton_partner(partner: Partner) -> bool:
    return partner.name == PROTON_PARTNER_NAME


def perform_proton_account_unlink(current_user: User):
    proton_partner = get_proton_partner()
    partner_user = PartnerUser.get_by(
        user_id=current_user.id, partner_id=proton_partner.id
    )
    if partner_user is not None:
        PartnerUser.delete(partner_user.id)
    Session.commit()
    agent.record_custom_event("AccountUnlinked", {"partner": proton_partner.name})
