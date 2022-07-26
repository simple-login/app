from typing import Optional

from app.config import CONNECT_WITH_PROTON
from app.db import Session
from app.errors import ProtonPartnerNotSetUp
from app.models import Partner

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


def is_proton_partner(partner: Partner) -> str:
    return partner.name == PROTON_PARTNER_NAME


def is_connect_with_proton_enabled() -> bool:
    if CONNECT_WITH_PROTON:
        return True
    return False
