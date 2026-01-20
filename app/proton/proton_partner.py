from typing import Optional

from app.db import Session
from app.errors import ProtonPartnerNotSetUp
from app.models import Partner
from app.partner_utils import PartnerData

PROTON_PARTNER_NAME = "Proton"
_PROTON_PARTNER: Optional[Partner] = None


def get_proton_partner() -> PartnerData:
    global _PROTON_PARTNER
    if _PROTON_PARTNER is None:
        partner = Partner.get_by(name=PROTON_PARTNER_NAME)
        if partner is None:
            raise ProtonPartnerNotSetUp
        Session.expunge(partner)
        _PROTON_PARTNER = partner.to_partner_data()
    return _PROTON_PARTNER


def is_proton_partner(partner: Partner) -> bool:
    return partner.name == PROTON_PARTNER_NAME
